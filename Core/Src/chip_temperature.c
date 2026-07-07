/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    chip_temperature.c
  * @brief   Chip temperature derived from measured resistance (linear R-T model).
  ******************************************************************************
  */
/* USER CODE END Header */

#include "chip_temperature.h"

#include <stddef.h>

/* TODO(chip-rt-calibration): replace the placeholder constants below with the
 * actual chip/process calibration values. The chip on CN9 (4-wire Kelvin) is
 * heated by the forced current; its resistance is measured as R = V/I and the
 * temperature is inferred from the linear R-T relationship:
 *     R = R0 * (1 + alpha * (T - T0))
 * The values below are placeholders so the project compiles; reported
 * temperatures will be wrong until real R0/alpha/T0 are supplied. */
#define CHIP_TEMPERATURE_R0_OHM        37.33644f    /* resistance at T0 (ohms)       */
#define CHIP_TEMPERATURE_ALPHA_PER_C   0.00206754f    /* temperature coefficient (1/C) */
#define CHIP_TEMPERATURE_T0_C          20.0f     /* reference temperature (C)     */

/* Resistance at or below this is treated as "not measurable" (no current). */
#define CHIP_TEMPERATURE_MIN_RESISTANCE_OHM  0.001f

float ChipTemperature_FromResistance(float resistance_ohm)
{
  return CHIP_TEMPERATURE_T0_C +
         ((resistance_ohm - CHIP_TEMPERATURE_R0_OHM) /
          (CHIP_TEMPERATURE_ALPHA_PER_C * CHIP_TEMPERATURE_R0_OHM));
}

ChipTemperature_Status ChipTemperature_FromResistanceChecked(float resistance_ohm, float *temperature_c)
{
  if (temperature_c == NULL)
  {
    return CHIP_TEMPERATURE_INVALID_PARAM;
  }

  if (resistance_ohm <= CHIP_TEMPERATURE_MIN_RESISTANCE_OHM)
  {
    return CHIP_TEMPERATURE_NOT_AVAILABLE;
  }

  *temperature_c = ChipTemperature_FromResistance(resistance_ohm);
  return CHIP_TEMPERATURE_OK;
}
