package io.github.aliontory.imucollect

import android.hardware.SensorManager
import org.junit.Assert
import org.junit.Test

class ImuSampleTest {
    @Test
    fun encodeTest() {
        val messageType = MessageType.IMU_ACCEL
        val nowNs = System.nanoTime()
        val accuracy = SensorManager.SENSOR_STATUS_ACCURACY_MEDIUM.toByte()
        val x = 0f
        val y = 0f
        val z = 0f
        val imuSample = ImuSample(messageType, nowNs, accuracy, x, y, z)
        val byteArray = imuSample.encode(0)

        val failMessage = "앞 4 바이트(payload_len)가 00 00 00 0D (십진수 13) 여야 함."
        Assert.assertEquals(failMessage, 0x00.toByte(), byteArray[0])
        Assert.assertEquals(failMessage, 0x00.toByte(), byteArray[1])
        Assert.assertEquals(failMessage, 0x00.toByte(), byteArray[2])
        Assert.assertEquals(failMessage, 0x0D.toByte(), byteArray[3])

        Assert.assertEquals("메시지 타입이 보존되어야 함", messageType.code, byteArray[4])
    }
}