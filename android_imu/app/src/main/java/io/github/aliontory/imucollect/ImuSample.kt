package io.github.aliontory.imucollect

import java.nio.ByteBuffer
import java.nio.ByteOrder

enum class MessageType(val code: Byte){
    IMU_ACCEL(0x03),
    IMU_GYRO(0x04),
}

/**
 * IMU 센서 샘플
 */
data class ImuSample(
    val messageType: MessageType,
    val timestampNs: Long,
    val accuracy: Byte,
    val x: Float,
    val y: Float,
    val z: Float,
)
{
    companion object{
        const val HEADER_SIZE = 21
        const val IMU_PAYLOAD_SIZE = 13
        const val PACKET_SIZE = HEADER_SIZE + IMU_PAYLOAD_SIZE
    }

    /**
     * IMU 샘플으 34바이트 패킷으로 인코딩한 결과를 반환한다.
     *
     * 패킷 구조는 다음과 같다:
     *
     * HEADER (21바이트, 빅 엔디안)
     * - payload_len   uint32   = 13
     * - message_type  uint8    = 0x03 (accel) / 0x04
     * - timestamp_ns  int64    = SensorEvent.timestamp
     * - seq           int64    = 센서별 독립 시퀀스
     *
     * IMU_SAMPLE (13바이트)
     * - accuracy      uint8
     * - x, y, z       float32 × 3
     *
     * 합 34바이트
     *
     * @param seq 네트워크 송수신 시 패킷 유실을 검출하기 위한 시퀀스 번호.
     */
    fun encode(seq: Long): ByteArray{
        val buf = ByteBuffer.allocate(PACKET_SIZE).order(ByteOrder.BIG_ENDIAN)

        buf.putInt(IMU_PAYLOAD_SIZE)
        buf.put(messageType.code)
        buf.putLong(timestampNs)
        buf.putLong(seq)

        buf.put(accuracy)
        buf.putFloat(x)
        buf.putFloat(y)
        buf.putFloat(z)

        return buf.array()
    }
}