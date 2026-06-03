/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    board_temperature.h
  * @brief   Optional board temperature sensor wrapper.
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef BOARD_TEMPERATURE_H
#define BOARD_TEMPERATURE_H

#ifdef __cplusplus
extern "C" {
#endif

#include "sht3x.h"
#include <stdint.h>

typedef enum
{
  BOARD_TEMPERATURE_OK = 0,
  BOARD_TEMPERATURE_ERROR,
  BOARD_TEMPERATURE_TIMEOUT,
  BOARD_TEMPERATURE_CRC_ERROR,
  BOARD_TEMPERATURE_INVALID_PARAM,
  BOARD_TEMPERATURE_NOT_PRESENT
} BoardTemperature_Status;

typedef struct
{
  float temperature_c;
  float humidity_percent;
  uint8_t present;
} BoardTemperature_Sample;

BoardTemperature_Status BoardTemperature_Init(void);
BoardTemperature_Status BoardTemperature_Read(BoardTemperature_Sample *sample);
uint8_t BoardTemperature_IsPresent(void);
const char *BoardTemperature_StatusText(BoardTemperature_Status status);

#ifdef __cplusplus
}
#endif

#endif /* BOARD_TEMPERATURE_H */
