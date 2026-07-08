/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    board_uart.h
  * @brief   Board UART helpers for USB debug UART and RS485.
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef BOARD_UART_H
#define BOARD_UART_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32h7xx_hal.h"
#include <stddef.h>
#include <stdint.h>

typedef enum
{
  BOARD_UART_OK = 0,
  BOARD_UART_ERROR,
  BOARD_UART_TIMEOUT,
  BOARD_UART_INVALID_PARAM
} BoardUart_Status;

typedef enum
{
  BOARD_UART_PORT_DEBUG = 0,
  BOARD_UART_PORT_RS485
} BoardUart_Port;

void BoardUart_Init(UART_HandleTypeDef *debug_uart, UART_HandleTypeDef *rs485_uart);
BoardUart_Status BoardUart_Write(BoardUart_Port port, const uint8_t *data, size_t len, uint32_t timeout_ms);
BoardUart_Status BoardUart_WriteString(BoardUart_Port port, const char *text, uint32_t timeout_ms);
BoardUart_Status BoardUart_Printf(BoardUart_Port port, const char *format, ...);
BoardUart_Status BoardUart_Read(BoardUart_Port port, uint8_t *data, size_t len, uint32_t timeout_ms);

int __io_putchar(int ch);
int __io_getchar(void);

#ifdef __cplusplus
}
#endif

#endif /* BOARD_UART_H */
