/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    ad5667.h
  * @brief   AD5667R dual 16-bit I2C DAC driver.
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef AD5667_H
#define AD5667_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32h7xx_hal.h"
#include <stdint.h>

#define AD5667_DEFAULT_I2C_ADDRESS_7BIT 0x0Fu

typedef enum
{
  AD5667_OK = 0,
  AD5667_ERROR,
  AD5667_TIMEOUT,
  AD5667_INVALID_PARAM
} AD5667_Status;

typedef enum
{
  AD5667_CHANNEL_A = 0u,
  AD5667_CHANNEL_B = 1u,
  AD5667_CHANNEL_BOTH = 7u
} AD5667_Channel;

typedef struct
{
  I2C_HandleTypeDef *hi2c;
  uint8_t address_7bit;
  float full_scale_volts;
  uint32_t timeout_ms;
} AD5667_Handle;

AD5667_Status AD5667_Init(AD5667_Handle *dac);
AD5667_Status AD5667_SetVoltage(AD5667_Handle *dac, AD5667_Channel channel, float volts);
AD5667_Status AD5667_SetCode(AD5667_Handle *dac, AD5667_Channel channel, uint16_t code);
AD5667_Status AD5667_SetBothVoltage(AD5667_Handle *dac, float volts);
AD5667_Status AD5667_ClearToZero(AD5667_Handle *dac);
uint16_t AD5667_VoltsToCode(AD5667_Handle *dac, float volts);

#ifdef __cplusplus
}
#endif

#endif /* AD5667_H */
