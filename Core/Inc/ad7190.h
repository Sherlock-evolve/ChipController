/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    ad7190.h
  * @brief   AD7190 24-bit sigma-delta ADC driver.
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef AD7190_H
#define AD7190_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32h7xx_hal.h"
#include <stdint.h>

#define AD7190_FILTER_WORD_MIN      1u
#define AD7190_FILTER_WORD_MAX      1023u
#define AD7190_FILTER_WORD_DEFAULT  96u

typedef enum
{
  AD7190_OK = 0,
  AD7190_ERROR,
  AD7190_TIMEOUT,
  AD7190_BAD_ID,
  AD7190_INVALID_PARAM
} AD7190_Status;

typedef enum
{
  AD7190_GAIN_1 = 0,
  AD7190_GAIN_8 = 3,
  AD7190_GAIN_16 = 4,
  AD7190_GAIN_32 = 5,
  AD7190_GAIN_64 = 6,
  AD7190_GAIN_128 = 7
} AD7190_Gain;

typedef enum
{
  AD7190_CHANNEL_AIN1_AIN2 = (1u << 0),
  AD7190_CHANNEL_AIN3_AIN4 = (1u << 1),
  AD7190_CHANNEL_TEMP = (1u << 2),
  AD7190_CHANNEL_AIN2_AIN2 = (1u << 3),
  AD7190_CHANNEL_AIN1_AINCOM = (1u << 4),
  AD7190_CHANNEL_AIN2_AINCOM = (1u << 5),
  AD7190_CHANNEL_AIN3_AINCOM = (1u << 6),
  AD7190_CHANNEL_AIN4_AINCOM = (1u << 7)
} AD7190_Channel;

typedef struct
{
  SPI_HandleTypeDef *hspi;
  GPIO_TypeDef *sync_port;
  uint16_t sync_pin;
  float vref_volts;
  AD7190_Gain gain;
  uint16_t filter_word;
  uint32_t timeout_ms;
} AD7190_Handle;

typedef struct
{
  uint32_t raw_code;
  int32_t signed_code;
  uint8_t status;
  float voltage;
} AD7190_Reading;

AD7190_Status AD7190_Init(AD7190_Handle *adc);
AD7190_Status AD7190_Reset(AD7190_Handle *adc);
AD7190_Status AD7190_ReadId(AD7190_Handle *adc, uint8_t *id);
AD7190_Status AD7190_ReadStatus(AD7190_Handle *adc, uint8_t *status);
AD7190_Status AD7190_CalibrateZeroScale(AD7190_Handle *adc);
AD7190_Status AD7190_CalibrateFullScale(AD7190_Handle *adc);
AD7190_Status AD7190_Configure(AD7190_Handle *adc,
                               uint8_t channels,
                               AD7190_Gain gain,
                               uint8_t bipolar,
                               uint8_t buffer_enabled,
                               uint8_t chop_enabled);
AD7190_Status AD7190_SetFilterWord(AD7190_Handle *adc, uint16_t filter_word);
AD7190_Status AD7190_StartContinuous(AD7190_Handle *adc);
AD7190_Status AD7190_StartSingle(AD7190_Handle *adc);
AD7190_Status AD7190_WaitReady(AD7190_Handle *adc, uint8_t *status);
AD7190_Status AD7190_ReadData(AD7190_Handle *adc, uint8_t status, AD7190_Reading *reading);
AD7190_Status AD7190_ReadSingle(AD7190_Handle *adc, AD7190_Reading *reading);

float AD7190_ConvertBipolarCode(uint32_t raw_code, float vref_volts, AD7190_Gain gain);

#ifdef __cplusplus
}
#endif

#endif /* AD7190_H */
