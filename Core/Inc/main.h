/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32h7xx_hal.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* USER CODE BEGIN EFP */

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
#define AD_MOSI_Pin GPIO_PIN_1
#define AD_MOSI_GPIO_Port GPIOC
#define AD_MISO_Pin GPIO_PIN_2
#define AD_MISO_GPIO_Port GPIOC
#define Wakeup_Pin GPIO_PIN_0
#define Wakeup_GPIO_Port GPIOA
#define MN_MOSI_Pin GPIO_PIN_6
#define MN_MOSI_GPIO_Port GPIOA
#define MN_MISO_Pin GPIO_PIN_7
#define MN_MISO_GPIO_Port GPIOA
#define LED0_Pin GPIO_PIN_0
#define LED0_GPIO_Port GPIOB
#define LED1_Pin GPIO_PIN_1
#define LED1_GPIO_Port GPIOB
#define AD_SCLK_Pin GPIO_PIN_10
#define AD_SCLK_GPIO_Port GPIOB
#define CHIP2_Pin GPIO_PIN_10
#define CHIP2_GPIO_Port GPIOH
#define CHIP1_Pin GPIO_PIN_11
#define CHIP1_GPIO_Port GPIOH
#define RE485_Pin GPIO_PIN_8
#define RE485_GPIO_Port GPIOA
#define RS485_TX_Pin GPIO_PIN_9
#define RS485_TX_GPIO_Port GPIOA
#define RS485_RX_Pin GPIO_PIN_10
#define RS485_RX_GPIO_Port GPIOA
#define MN_NSS_Pin GPIO_PIN_15
#define MN_NSS_GPIO_Port GPIOA
#define USB_TX_Pin GPIO_PIN_5
#define USB_TX_GPIO_Port GPIOD
#define USB_RX_Pin GPIO_PIN_6
#define USB_RX_GPIO_Port GPIOD
#define MN_CLK_Pin GPIO_PIN_11
#define MN_CLK_GPIO_Port GPIOG
#define SPI2_SYNC_Pin GPIO_PIN_12
#define SPI2_SYNC_GPIO_Port GPIOG
#define SPI1_SYNC_Pin GPIO_PIN_13
#define SPI1_SYNC_GPIO_Port GPIOG
#define DAC_ADDR_Pin GPIO_PIN_3
#define DAC_ADDR_GPIO_Port GPIOB
#define DAC_CLR_Pin GPIO_PIN_4
#define DAC_CLR_GPIO_Port GPIOB
#define DAC_LDAC_Pin GPIO_PIN_5
#define DAC_LDAC_GPIO_Port GPIOB
#define SHT_SCL_Pin GPIO_PIN_6
#define SHT_SCL_GPIO_Port GPIOB
#define SHT_SDA_Pin GPIO_PIN_7
#define SHT_SDA_GPIO_Port GPIOB

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
