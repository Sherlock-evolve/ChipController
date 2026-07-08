/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    chip_temperature.c
  * @brief   Chip temperature derived from measured resistance (piecewise R-T table).
  ******************************************************************************
  */
/* USER CODE END Header */

#include "chip_temperature.h"

#include <stddef.h>

typedef struct
{
  float resistance_ohm;
  float temperature_c;
} ChipTemperature_Point;

static const ChipTemperature_Point s_chip_temperature_table[] = {
  {21.0f, -175.0f},
  {22.0f, -169.0f},
  {24.0f, -158.0f},
  {25.0f, -148.0f},
  {27.0f, -122.0f},
  {28.0f, -102.0f},
  {30.0f, -84.0f},
  {32.0f, -56.0f},
  {33.0f, -36.0f},
  {35.0f, -13.0f},
  {36.0f, 10.0f},
  {37.0f, 23.0f},
};

#define CHIP_TEMPERATURE_TABLE_COUNT \
  (sizeof(s_chip_temperature_table) / sizeof(s_chip_temperature_table[0]))

/* Resistance at or below this is treated as "not measurable" (no current). */
#define CHIP_TEMPERATURE_MIN_RESISTANCE_OHM  0.001f

static float chip_temperature_interpolate(const ChipTemperature_Point *low,
                                          const ChipTemperature_Point *high,
                                          float resistance_ohm)
{
  float resistance_span_ohm = high->resistance_ohm - low->resistance_ohm;
  float temperature_span_c = high->temperature_c - low->temperature_c;

  if (resistance_span_ohm == 0.0f)
  {
    return low->temperature_c;
  }

  return low->temperature_c +
         ((resistance_ohm - low->resistance_ohm) * temperature_span_c / resistance_span_ohm);
}

float ChipTemperature_FromResistance(float resistance_ohm)
{
  size_t index;
  size_t last_index = CHIP_TEMPERATURE_TABLE_COUNT - 1u;

  if (resistance_ohm <= s_chip_temperature_table[0].resistance_ohm)
  {
    return chip_temperature_interpolate(&s_chip_temperature_table[0],
                                        &s_chip_temperature_table[1],
                                        resistance_ohm);
  }

  if (resistance_ohm >= s_chip_temperature_table[last_index].resistance_ohm)
  {
    return chip_temperature_interpolate(&s_chip_temperature_table[last_index - 1u],
                                        &s_chip_temperature_table[last_index],
                                        resistance_ohm);
  }

  for (index = 0u; index < last_index; index++)
  {
    if (resistance_ohm <= s_chip_temperature_table[index + 1u].resistance_ohm)
    {
      return chip_temperature_interpolate(&s_chip_temperature_table[index],
                                          &s_chip_temperature_table[index + 1u],
                                          resistance_ohm);
    }
  }

  return s_chip_temperature_table[last_index].temperature_c;
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
