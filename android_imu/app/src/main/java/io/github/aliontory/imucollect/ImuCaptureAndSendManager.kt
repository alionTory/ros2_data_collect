package io.github.aliontory.imucollect

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlin.time.Duration.Companion.milliseconds

class ImuCaptureAndSendManager(context: Context) {
    private val imuSampler = ImuSampler(context)
    private var imuPacketSender: ImuPacketSender? = null

    private var lastImuPacketSenderSnapshot = ImuPacketSenderSnapshot()

    var isActive = false
        private set

    /**
     * [isActive]가 false 인 경우, IMU 데이터 수집 및 전송을 시작한다.
     *
     * [isActive]가 true 인 경우 바로 리턴한다.
     *
     * ensure: isActive
     */
    fun start(host: String, port: Int) {
        if (!isActive) {
            isActive = true
            val imuPacketSender = ImuPacketSender(host, port, imuSampler.queue)
            this.imuPacketSender = imuPacketSender
            imuPacketSender.start()
            imuSampler.start()
        }
    }

    /**
     * [isActive]가 true 경우, IMU 데이터 수집 및 전송을 중지한다.
     *
     * [isActive]가 false 경우 바로 리턴한다.
     *
     * ensure: !isActive
     */
    fun stop() {
        if (isActive) {
            isActive = false
            imuSampler.stop()
            val imuPacketSender = this.imuPacketSender
            check(imuPacketSender != null)
            CoroutineScope(Dispatchers.IO).launch {
                imuPacketSender.stop(200.milliseconds)
            }
            this.imuPacketSender = null
        }
    }

    val imuSamplerSnapshot: ImuSamplerSnapshot
        get() = imuSampler.snapshot()

    val imuPacketSenderSnapshot: ImuPacketSenderSnapshot
        get() {
            val imuPacketSender = this.imuPacketSender
            if (imuPacketSender != null) {
                lastImuPacketSenderSnapshot = imuPacketSender.snapshot()
            }
            return lastImuPacketSenderSnapshot
        }

    /**
     * 센서 시계와 폰 시계 타임스탬프 값 차이 기록을 초기화한다.
     */
    fun resetClockDelta() {
        imuSampler.resetClockDelta()
    }
}