/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    sht3x.h
  * @brief   Sensirion SHT3x temperature/humidity I2C driver.
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef SHT3X_H
#define SHT3X_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32h7xx_hal.h"
#include <stdint.h>

#define SHT3X_I2C_ADDRESS_PRIMARY_7BIT   0x44u
#define SHT3X_I2C_ADDRESS_SECONDARY_7BIT 0x45u

typedef enum
{
  SHT3X_OK = 0,
  SHT3X_ERROR,
  SHT3X_TIMEOUT,
  SHT3X_CRC_ERROR,
  SHT3X_INVALID_PARAM
} SHT3X_Status;

typedef struct
{
  I2C_HandleTypeDef *hi2c;
  uint8_t address_7bit;
  uint32_t timeout_ms;
} SHT3X_Handle;

typedef struct
{
  float temperature_c;
  float humidity_percent;
} SHT3X_Sample;

SHT3X_Status SHT3X_Init(SHT3X_Handle *sensor);
SHT3X_Status SHT3X_Read(SHT3X_Handle *sensor, SHT3X_Sample *sample);
SHT3X_Status SHT3X_SoftReset(SHT3X_Handle *sensor);
const char *SHT3X_StatusText(SHT3X_Status status);

#ifdef __cplusplus
}
#endif

#endif /* SHT3X_H */
