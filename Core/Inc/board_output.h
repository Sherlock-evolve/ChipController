/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    board_output.h
  * @brief   Safe board output control and R42 self-test loop.
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef BOARD_OUTPUT_H
#define BOARD_OUTPUT_H

#ifdef __cplusplus
extern "C" {
#endif

#include "ad5667.h"
#include "chip_measure.h"
#include <stdint.h>

typedef enum
{
  BOARD_OUTPUT_OK = 0,
  BOARD_OUTPUT_ERROR,
  BOARD_OUTPUT_TIMEOUT,
  BOARD_OUTPUT_INVALID_PARAM,
  BOARD_OUTPUT_LIMIT_CLAMPED,
  BOARD_OUTPUT_OVERCURRENT,
  BOARD_OUTPUT_NO_CURRENT,
  BOARD_OUTPUT_R42_OUT_OF_RANGE
} BoardOutput_Status;

typedef struct
{
  float requested_drive_v;
  float applied_drive_v;
  float current_a;
  float current_sense_v;
  float load_voltage_raw_v;
  float load_voltage_v;
  float resistance_ohm;
  uint8_t passed;
} BoardOutput_R42SelfTestResult;

BoardOutput_Status BoardOutput_Init(void);
BoardOutput_Status BoardOutput_SetDriveVoltage(float volts);
BoardOutput_Status BoardOutput_SetZero(void);
BoardOutput_Status BoardOutput_RunR42SelfTest(BoardOutput_R42SelfTestResult *result);
float BoardOutput_GetMaxDriveVoltage(void);
const char *BoardOutput_StatusText(BoardOutput_Status status);

#ifdef __cplusplus
}
#endif

#endif /* BOARD_OUTPUT_H */
