/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    board_uart.c
  * @brief   Board UART helpers for USB debug UART and RS485.
  ******************************************************************************
  */
/* USER CODE END Header */

#include "board_uart.h"
#include "main.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#define BOARD_UART_DEFAULT_TIMEOUT_MS 100u
#define BOARD_UART_PRINTF_BUFFER_SIZE 384u
#define BOARD_UART_RS485_TURNAROUND_DELAY_MS 1u
#define BOARD_UART_RX_RING_SIZE        256u

static UART_HandleTypeDef *s_debug_uart;
static UART_HandleTypeDef *s_rs485_uart;

/* Interrupt-driven receive ring buffer for debug UART. */
static uint8_t  s_debug_rx_ring[BOARD_UART_RX_RING_SIZE];
static volatile uint16_t s_debug_rx_head;   /* ISR writes here */
static uint16_t s_debug_rx_tail;            /* main loop reads here */
static uint8_t  s_debug_rx_it_byte;         /* HAL_UART_Receive_IT target byte */

static UART_HandleTypeDef *board_uart_get_handle(BoardUart_Port port);
static BoardUart_Status board_uart_from_hal(HAL_StatusTypeDef status);
static void board_uart_rs485_set_tx(uint8_t enabled);
static uint8_t board_uart_debug_rx_pop(uint8_t *byte);

void BoardUart_Init(UART_HandleTypeDef *debug_uart, UART_HandleTypeDef *rs485_uart)
{
  s_debug_uart = debug_uart;
  s_rs485_uart = rs485_uart;
  board_uart_rs485_set_tx(0u);

  s_debug_rx_head = 0u;
  s_debug_rx_tail = 0u;

  /* Start interrupt-driven receive for the debug port. */
  if (s_debug_uart != NULL)
  {
    (void)HAL_UART_Receive_IT(s_debug_uart, &s_debug_rx_it_byte, 1u);
  }
}

BoardUart_Status BoardUart_Write(BoardUart_Port port, const uint8_t *data, size_t len, uint32_t timeout_ms)
{
  UART_HandleTypeDef *uart;
  HAL_StatusTypeDef hal_status;

  if ((data == NULL) && (len > 0u))
  {
    return BOARD_UART_INVALID_PARAM;
  }

  if (len == 0u)
  {
    return BOARD_UART_OK;
  }

  if (len > UINT16_MAX)
  {
    return BOARD_UART_INVALID_PARAM;
  }

  uart = board_uart_get_handle(port);
  if (uart == NULL)
  {
    return BOARD_UART_INVALID_PARAM;
  }

  if (port == BOARD_UART_PORT_RS485)
  {
    board_uart_rs485_set_tx(1u);
    HAL_Delay(BOARD_UART_RS485_TURNAROUND_DELAY_MS);
  }

  hal_status = HAL_UART_Transmit(uart, (uint8_t *)data, (uint16_t)len, timeout_ms);

  if (port == BOARD_UART_PORT_RS485)
  {
    HAL_Delay(BOARD_UART_RS485_TURNAROUND_DELAY_MS);
    board_uart_rs485_set_tx(0u);
  }

  return board_uart_from_hal(hal_status);
}

BoardUart_Status BoardUart_WriteString(BoardUart_Port port, const char *text, uint32_t timeout_ms)
{
  if (text == NULL)
  {
    return BOARD_UART_INVALID_PARAM;
  }

  return BoardUart_Write(port, (const uint8_t *)text, strlen(text), timeout_ms);
}

BoardUart_Status BoardUart_Printf(BoardUart_Port port, const char *format, ...)
{
  char buffer[BOARD_UART_PRINTF_BUFFER_SIZE];
  va_list args;
  int len;

  if (format == NULL)
  {
    return BOARD_UART_INVALID_PARAM;
  }

  va_start(args, format);
  len = vsnprintf(buffer, sizeof(buffer), format, args);
  va_end(args);

  if (len < 0)
  {
    return BOARD_UART_ERROR;
  }

  if ((size_t)len >= sizeof(buffer))
  {
    len = (int)sizeof(buffer) - 1;
  }

  return BoardUart_Write(port, (const uint8_t *)buffer, (size_t)len, BOARD_UART_DEFAULT_TIMEOUT_MS);
}

BoardUart_Status BoardUart_Read(BoardUart_Port port, uint8_t *data, size_t len, uint32_t timeout_ms)
{
  UART_HandleTypeDef *uart;
  HAL_StatusTypeDef hal_status;

  if ((data == NULL) || (len == 0u) || (len > UINT16_MAX))
  {
    return BOARD_UART_INVALID_PARAM;
  }

  uart = board_uart_get_handle(port);
  if (uart == NULL)
  {
    return BOARD_UART_INVALID_PARAM;
  }

  if (port == BOARD_UART_PORT_RS485)
  {
    board_uart_rs485_set_tx(0u);

    hal_status = HAL_UART_Receive(uart, data, (uint16_t)len, timeout_ms);
    if (hal_status == HAL_ERROR)
    {
      __HAL_UART_CLEAR_FLAG(uart, UART_CLEAR_PEF | UART_CLEAR_FEF | UART_CLEAR_NEF | UART_CLEAR_OREF);
    }

    return board_uart_from_hal(hal_status);
  }

  /* Debug port: read from interrupt-driven ring buffer. */
  {
    uint32_t deadline = HAL_GetTick() + timeout_ms;
    size_t read = 0u;

    while (read < len)
    {
      if (board_uart_debug_rx_pop(&data[read]) != 0u)
      {
        read++;
        continue;
      }

      if (read > 0u)
      {
        return BOARD_UART_OK;
      }

      if (timeout_ms == 0u)
      {
        return BOARD_UART_TIMEOUT;
      }

      if ((int32_t)(HAL_GetTick() - deadline) >= 0)
      {
        return BOARD_UART_TIMEOUT;
      }
    }

    return BOARD_UART_OK;
  }
}

int __io_putchar(int ch)
{
  uint8_t byte = (uint8_t)ch;

  if (s_debug_uart == NULL)
  {
    return ch;
  }

  (void)HAL_UART_Transmit(s_debug_uart, &byte, 1u, BOARD_UART_DEFAULT_TIMEOUT_MS);
  return ch;
}

int __io_getchar(void)
{
  uint8_t byte = 0u;

  if (s_debug_uart == NULL)
  {
    return -1;
  }

  /* Spin until a byte arrives from the interrupt-driven ring buffer. */
  while (board_uart_debug_rx_pop(&byte) == 0u)
  {
  }

  return (int)byte;
}

static UART_HandleTypeDef *board_uart_get_handle(BoardUart_Port port)
{
  switch (port)
  {
    case BOARD_UART_PORT_DEBUG:
      return s_debug_uart;
    case BOARD_UART_PORT_RS485:
      return s_rs485_uart;
    default:
      return NULL;
  }
}

static BoardUart_Status board_uart_from_hal(HAL_StatusTypeDef status)
{
  switch (status)
  {
    case HAL_OK:
      return BOARD_UART_OK;
    case HAL_TIMEOUT:
      return BOARD_UART_TIMEOUT;
    case HAL_ERROR:
    case HAL_BUSY:
    default:
      return BOARD_UART_ERROR;
  }
}

static void board_uart_rs485_set_tx(uint8_t enabled)
{
  /* TD301D485H CON: low = transmit, high = receive. */
  HAL_GPIO_WritePin(RE485_GPIO_Port, RE485_Pin, enabled ? GPIO_PIN_RESET : GPIO_PIN_SET);
}

static uint8_t board_uart_debug_rx_pop(uint8_t *byte)
{
  uint16_t tail;

  if (byte == NULL)
  {
    return 0u;
  }

  __disable_irq();
  tail = s_debug_rx_tail;
  if (s_debug_rx_head != tail)
  {
    *byte = s_debug_rx_ring[tail];
    s_debug_rx_tail = (tail + 1u) % BOARD_UART_RX_RING_SIZE;
    __enable_irq();
    return 1u;
  }
  __enable_irq();

  return 0u;
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
  if ((s_debug_uart != NULL) && (huart->Instance == s_debug_uart->Instance))
  {
    uint16_t next = (s_debug_rx_head + 1u) % BOARD_UART_RX_RING_SIZE;

    /* Drop byte if ring is full (never happens at 115200 with 256-byte ring). */
    if (next != s_debug_rx_tail)
    {
      s_debug_rx_ring[s_debug_rx_head] = s_debug_rx_it_byte;
      s_debug_rx_head = next;
    }

    (void)HAL_UART_Receive_IT(s_debug_uart, &s_debug_rx_it_byte, 1u);
  }
}
