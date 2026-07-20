/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    chip_temperature.c
  * @brief   Chip temperature derived from a two-point linear TCR model.
  ******************************************************************************
  */
/* USER CODE END Header */

#include "chip_temperature.h"

#include <stddef.h>

/* Two-point model derived from the project-root "tcr" data file.
 * The two low-temperature measurements are averaged into one endpoint:
 *   low:       R = 21.434657 Ohm, T = -177.699500 C
 *   reference: R = 40.230272 Ohm, T =   20.776000 C
 * R(T) = Rref * (1 + alpha * (T - Tref)). */
#define CHIP_TEMPERATURE_REFERENCE_RESISTANCE_OHM  40.230272f
#define CHIP_TEMPERATURE_REFERENCE_TEMPERATURE_C   20.776000f
#define CHIP_TEMPERATURE_TCR_PER_C                   0.002353946928f

/* Resistance at or below this is treated as "not measurable" (no current). */
#define CHIP_TEMPERATURE_MIN_RESISTANCE_OHM  0.001f

float ChipTemperature_FromResistance(float resistance_ohm)
{
  return CHIP_TEMPERATURE_REFERENCE_TEMPERATURE_C +
         ((resistance_ohm - CHIP_TEMPERATURE_REFERENCE_RESISTANCE_OHM) /
          (CHIP_TEMPERATURE_TCR_PER_C * CHIP_TEMPERATURE_REFERENCE_RESISTANCE_OHM));
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
