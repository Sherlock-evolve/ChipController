/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    chip_measure.h
  * @brief   Board-level measurement helpers for the chip controller board.
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef CHIP_MEASURE_H
#define CHIP_MEASURE_H

#ifdef __cplusplus
extern "C" {
#endif

#include "ad7190.h"
#include <stdint.h>

#define CHIP_MEASURE_SYNC_FILTER_ALPHA 0.25f

typedef enum
{
  CHIP_MEASURE_OK = 0,
  CHIP_MEASURE_ERROR,
  CHIP_MEASURE_TIMEOUT,
  CHIP_MEASURE_BAD_ID,
  CHIP_MEASURE_INVALID_PARAM,
  CHIP_MEASURE_NO_CURRENT
} ChipMeasure_Status;

typedef enum
{
  CHIP_MEASURE_PATH_EXTERNAL = 0,
  CHIP_MEASURE_PATH_INTERNAL_R42
} ChipMeasure_Path;

typedef struct
{
  float current_sense_voltage_v;
  float current_a;
  float load_voltage_raw_v;
  float load_voltage_v;
  float resistance_ohm;
  uint8_t resistance_valid;
} ChipMeasure_R42Sample;

typedef struct
{
  float current_sense_voltage_v;
  float current_a;
  float load_voltage_raw_v;
  float load_voltage_v;
  uint8_t current_adc_status;
  uint8_t voltage_adc_status;
} ChipMeasure_SyncSample;

typedef struct
{
  ChipMeasure_SyncSample sample;
  ChipMeasure_Path path;
  uint8_t valid;
} ChipMeasure_SyncFilter;

ChipMeasure_Status ChipMeasure_Init(void);
ChipMeasure_Status ChipMeasure_ReadAdcIds(uint8_t *current_adc_id, uint8_t *voltage_adc_id);
ChipMeasure_Status ChipMeasure_SelectPath(ChipMeasure_Path path);
ChipMeasure_Status ChipMeasure_ReadCurrent(ChipMeasure_Path path, float *current_a, float *sense_voltage_v);
ChipMeasure_Status ChipMeasure_ReadLoadVoltage(ChipMeasure_Path path,
                                               float *load_voltage_v,
                                               float *raw_voltage_v);
ChipMeasure_Status ChipMeasure_ReadSynchronized(ChipMeasure_Path path, ChipMeasure_SyncSample *sample);
void ChipMeasure_ResetSyncFilter(ChipMeasure_SyncFilter *filter);
ChipMeasure_Status ChipMeasure_FilterSynchronized(ChipMeasure_Path path,
                                                 const ChipMeasure_SyncSample *input,
                                                 ChipMeasure_SyncFilter *filter,
                                                 ChipMeasure_SyncSample *output);
ChipMeasure_Status ChipMeasure_ReadSynchronizedFiltered(ChipMeasure_Path path,
                                                       ChipMeasure_SyncFilter *filter,
                                                       ChipMeasure_SyncSample *sample);
ChipMeasure_Status ChipMeasure_ReadInternalR42(ChipMeasure_R42Sample *sample);
uint8_t ChipMeasure_ComputeExternalResistance(float load_voltage_v,
                                               float total_current_a,
                                               float *resistance_ohm);

#ifdef __cplusplus
}
#endif

#endif /* CHIP_MEASURE_H */
