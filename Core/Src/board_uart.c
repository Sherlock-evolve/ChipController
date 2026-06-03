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

static UART_HandleTypeDef *s_debug_uart;
static UART_HandleTypeDef *s_rs485_uart;

static UART_HandleTypeDef *board_uart_get_handle(BoardUart_Port port);
static BoardUart_Status board_uart_from_hal(HAL_StatusTypeDef status);
static void board_uart_rs485_set_tx(uint8_t enabled);

void BoardUart_Init(UART_HandleTypeDef *debug_uart, UART_HandleTypeDef *rs485_uart)
{
  s_debug_uart = debug_uart;
  s_rs485_uart = rs485_uart;
  board_uart_rs485_set_tx(0u);
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
  }

  hal_status = HAL_UART_Transmit(uart, (uint8_t *)data, (uint16_t)len, timeout_ms);

  if (port == BOARD_UART_PORT_RS485)
  {
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
  }

  return board_uart_from_hal(HAL_UART_Receive(uart, data, (uint16_t)len, timeout_ms));
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

  if (HAL_UART_Receive(s_debug_uart, &byte, 1u, HAL_MAX_DELAY) != HAL_OK)
  {
    return -1;
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
