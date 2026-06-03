################################################################################
# Automatically-generated file. Do not edit!
# Toolchain: GNU Tools for STM32 (14.3.rel1)
################################################################################

# Add inputs and outputs from these tool invocations to the build variables 
C_SRCS += \
../Core/Src/ad5667.c \
../Core/Src/ad7190.c \
../Core/Src/board_output.c \
../Core/Src/board_protocol.c \
../Core/Src/board_temperature.c \
../Core/Src/board_uart.c \
../Core/Src/chip_measure.c \
../Core/Src/main.c \
../Core/Src/sht3x.c \
../Core/Src/stm32h7xx_hal_msp.c \
../Core/Src/stm32h7xx_it.c \
../Core/Src/syscalls.c \
../Core/Src/sysmem.c \
../Core/Src/system_stm32h7xx.c \
../Core/Src/thermal_control.c 

OBJS += \
./Core/Src/ad5667.o \
./Core/Src/ad7190.o \
./Core/Src/board_output.o \
./Core/Src/board_protocol.o \
./Core/Src/board_temperature.o \
./Core/Src/board_uart.o \
./Core/Src/chip_measure.o \
./Core/Src/main.o \
./Core/Src/sht3x.o \
./Core/Src/stm32h7xx_hal_msp.o \
./Core/Src/stm32h7xx_it.o \
./Core/Src/syscalls.o \
./Core/Src/sysmem.o \
./Core/Src/system_stm32h7xx.o \
./Core/Src/thermal_control.o 

C_DEPS += \
./Core/Src/ad5667.d \
./Core/Src/ad7190.d \
./Core/Src/board_output.d \
./Core/Src/board_protocol.d \
./Core/Src/board_temperature.d \
./Core/Src/board_uart.d \
./Core/Src/chip_measure.d \
./Core/Src/main.d \
./Core/Src/sht3x.d \
./Core/Src/stm32h7xx_hal_msp.d \
./Core/Src/stm32h7xx_it.d \
./Core/Src/syscalls.d \
./Core/Src/sysmem.d \
./Core/Src/system_stm32h7xx.d \
./Core/Src/thermal_control.d 


# Each subdirectory must supply rules for building sources it contributes
Core/Src/%.o Core/Src/%.su Core/Src/%.cyclo: ../Core/Src/%.c Core/Src/subdir.mk
	arm-none-eabi-gcc "$<" -mcpu=cortex-m7 -std=gnu11 -g3 -DDEBUG -DUSE_PWR_LDO_SUPPLY -DUSE_HAL_DRIVER -DSTM32H753xx -c -I../Core/Inc -I../Drivers/STM32H7xx_HAL_Driver/Inc -I../Drivers/STM32H7xx_HAL_Driver/Inc/Legacy -I../Drivers/CMSIS/Device/ST/STM32H7xx/Include -I../Drivers/CMSIS/Include -O0 -ffunction-sections -fdata-sections -Wall -fstack-usage -fcyclomatic-complexity -MMD -MP -MF"$(@:%.o=%.d)" -MT"$@" --specs=nano.specs -mfpu=fpv5-d16 -mfloat-abi=hard -mthumb -o "$@"

clean: clean-Core-2f-Src

clean-Core-2f-Src:
	-$(RM) ./Core/Src/ad5667.cyclo ./Core/Src/ad5667.d ./Core/Src/ad5667.o ./Core/Src/ad5667.su ./Core/Src/ad7190.cyclo ./Core/Src/ad7190.d ./Core/Src/ad7190.o ./Core/Src/ad7190.su ./Core/Src/board_output.cyclo ./Core/Src/board_output.d ./Core/Src/board_output.o ./Core/Src/board_output.su ./Core/Src/board_protocol.cyclo ./Core/Src/board_protocol.d ./Core/Src/board_protocol.o ./Core/Src/board_protocol.su ./Core/Src/board_temperature.cyclo ./Core/Src/board_temperature.d ./Core/Src/board_temperature.o ./Core/Src/board_temperature.su ./Core/Src/board_uart.cyclo ./Core/Src/board_uart.d ./Core/Src/board_uart.o ./Core/Src/board_uart.su ./Core/Src/chip_measure.cyclo ./Core/Src/chip_measure.d ./Core/Src/chip_measure.o ./Core/Src/chip_measure.su ./Core/Src/main.cyclo ./Core/Src/main.d ./Core/Src/main.o ./Core/Src/main.su ./Core/Src/sht3x.cyclo ./Core/Src/sht3x.d ./Core/Src/sht3x.o ./Core/Src/sht3x.su ./Core/Src/stm32h7xx_hal_msp.cyclo ./Core/Src/stm32h7xx_hal_msp.d ./Core/Src/stm32h7xx_hal_msp.o ./Core/Src/stm32h7xx_hal_msp.su ./Core/Src/stm32h7xx_it.cyclo ./Core/Src/stm32h7xx_it.d ./Core/Src/stm32h7xx_it.o ./Core/Src/stm32h7xx_it.su ./Core/Src/syscalls.cyclo ./Core/Src/syscalls.d ./Core/Src/syscalls.o ./Core/Src/syscalls.su ./Core/Src/sysmem.cyclo ./Core/Src/sysmem.d ./Core/Src/sysmem.o ./Core/Src/sysmem.su ./Core/Src/system_stm32h7xx.cyclo ./Core/Src/system_stm32h7xx.d ./Core/Src/system_stm32h7xx.o ./Core/Src/system_stm32h7xx.su ./Core/Src/thermal_control.cyclo ./Core/Src/thermal_control.d ./Core/Src/thermal_control.o ./Core/Src/thermal_control.su

.PHONY: clean-Core-2f-Src

