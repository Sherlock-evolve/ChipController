/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    board_protocol.h
  * @brief   RS485 ASCII protocol for bring-up and control.
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef BOARD_PROTOCOL_H
#define BOARD_PROTOCOL_H

#ifdef __cplusplus
extern "C" {
#endif

void BoardProtocol_Init(void);
void BoardProtocol_Poll(void);

#ifdef __cplusplus
}
#endif

#endif /* BOARD_PROTOCOL_H */
