/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    chip_temperature.h
  * @brief   Chip temperature derived from measured resistance (two-point TCR model).
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef CHIP_TEMPERATURE_H
#define CHIP_TEMPERATURE_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

typedef enum
{
  CHIP_TEMPERATURE_OK = 0,
  CHIP_TEMPERATURE_INVALID_PARAM,
  CHIP_TEMPERATURE_NOT_AVAILABLE
} ChipTemperature_Status;

/**
  * @brief  Convert chip resistance to temperature using
  *           R = Rref * (1 + alpha * (T - Tref)).
  * @param  resistance_ohm  Chip resistance in ohms (must be > 0).
  * @retval Temperature in degrees Celsius.
  */
float ChipTemperature_FromResistance(float resistance_ohm);

/**
  * @brief  Checked variant that validates the input before converting.
  * @param  resistance_ohm  Chip resistance in ohms.
  * @param  temperature_c   Output temperature in degrees Celsius (set on OK).
  * @retval CHIP_TEMPERATURE_OK on success,
  *         CHIP_TEMPERATURE_NOT_AVAILABLE when resistance is not measurable,
  *         CHIP_TEMPERATURE_INVALID_PARAM on NULL/invalid input.
  */
ChipTemperature_Status ChipTemperature_FromResistanceChecked(float resistance_ohm, float *temperature_c);

#ifdef __cplusplus
}
#endif

#endif /* CHIP_TEMPERATURE_H */
