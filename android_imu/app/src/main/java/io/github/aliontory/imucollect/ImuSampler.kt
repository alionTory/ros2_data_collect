package io.github.aliontory.imucollect

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.SystemClock
import android.util.Log
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.ReceiveChannel

/** 센서 정보를 담는 타입 */
data class SensorSnapshot(
    /**
     * 가속도계 센서 데이터 수집 횟수.
     */
    val accelCount: Long = 0L,
    /**
     * 가속도계 센서 데이터 수집율(Hz).
     */
    val accelHz: Double? = null,
    /**
     * 가속도계 센서 데이터 수집 간격이 경계치를 초과한 횟수.
     */
    val accelGapExceedCount: Long = 0L,
    /**
     * 자이로스코프 센서 데이터 수집 횟수.
     */
    val gyroCount: Long = 0L,
    /**
     * 자이로스코프 센서 데이터 수집율(Hz).
     */
    val gyroHz: Double? = null,
    /**
     * 자이로스코프 센서 데이터 수집 간격이 경계치를 초과한 횟수.
     */
    val gyroGapExceedCount: Long = 0L,

    /**
     * 센서 시계와 폰 시계 타임스탬프 값 차이.
     */
    val clockDeltaLastNs: Long = 0L,
    val clockDeltaMinNs: Long = 0L,
    val clockDeltaMaxNs: Long = 0L,

    /**
     * 큐 공간이 부족해서 enqueue에 실패한 횟수
     */
    val queueOverflowCount: Long = 0L,
)

/**
 * [update]에서 주어진 값들의 가장 최근값, 최솟값, 최댓값을 기록.
 */
class MinMaxLast {
    /**
     * 최근값. 초기값은 0L.
     */
    var last = 0L
        private set

    var min = Long.MAX_VALUE
        private set
    var max = Long.MIN_VALUE
        private set

    fun update(newValue: Long) {
        last = newValue
        if (newValue < min)
            min = newValue
        if (max < newValue)
            max = newValue
    }
}

/**
 * 센서로부터 IMU 데이터를 받아 큐에 저장한다.
 */
class ImuSampler(context: Context) {
    companion object {
        private const val TAG = "ImuSampler"

        const val SAMPLING_RATE_HZ = 52

        /** 요청값이며 보장이 아니다. */
        const val SAMPLING_PERIOD_US = 1e6.toInt() / SAMPLING_RATE_HZ

        private const val GAP_THRESHOLD_NS = SAMPLING_PERIOD_US * 1e3.toLong() * 3
    }

    private val sensorManager =
        context.getSystemService(Context.SENSOR_SERVICE) as SensorManager

    private val accelerometer: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val gyroscope: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)

    private var accelerometerWindow = SensorWindow(GAP_THRESHOLD_NS)
    private var gyroscopeWindow = SensorWindow(GAP_THRESHOLD_NS)

    private var queueOverflowCount = 0L

    /**
     * 센서 시계와 폰 시계 타임스탬프 값 차이.
     */
    private var clockDelta = MinMaxLast()

    /**
     * 센서 시계와 폰 시계 타임스탬프 값 차이 기록을 초기화한다.
     */
    fun resetClockDelta() {
        clockDelta = MinMaxLast()
    }

    private var _queue = Channel<ImuSample>()

    /**
     * [start] 호출 이후 IMU 데이터가 저장될 큐.
     */
    val queue: ReceiveChannel<ImuSample>
        get() = _queue

    private val sensorEventListener = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            clockDelta.update(SystemClock.elapsedRealtimeNanos() - event.timestamp)

            val messageType = when (event.sensor.type) {
                Sensor.TYPE_ACCELEROMETER -> MessageType.IMU_ACCEL
                Sensor.TYPE_GYROSCOPE     -> MessageType.IMU_GYRO
                else -> {
                    Log.e(TAG, "예상치 못한 센서 타입: ${event.sensor.type}")
                    return
                }
            }

            when (messageType) {
                MessageType.IMU_ACCEL -> accelerometerWindow.add(event.timestamp)
                MessageType.IMU_GYRO -> gyroscopeWindow.add(event.timestamp)
            }

            val enqueueResult = _queue.trySend(ImuSample(messageType, event.timestamp, event.accuracy.toByte(), event.values[0], event.values[1], event.values[2]))

            if(enqueueResult.isFailure){
                if(enqueueResult.isClosed)
                    Log.e(TAG, "enqueue 실패 - 큐가 닫혀 있음.")
                else
                    queueOverflowCount += 1
            }
        }

        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
            Log.i(TAG, "센서 ${sensor?.name}의 accurcy가 $accuracy 로 변경됨.")
        }
    }

    /**
     * [ImuSampler] 객체를 활성화한다.
     * @return 활성화에 성공했으면 true
     */
    fun start(): Boolean {
        val result = isSensorExist() && registerListners()
        check(accelerometer != null)
        check(gyroscope != null)

        if (result) {
            Log.i(TAG, "${ImuSampler::class.simpleName} 객체 활성화 성공")
            Log.i(
                TAG, "${accelerometer.name} / ${accelerometer.vendor} / " +
                        "minDelay=${accelerometer.minDelay}us / maxDelay=${accelerometer.maxDelay}us / " +
                        "fifo=${accelerometer.fifoMaxEventCount}"
            )
            Log.i(
                TAG, "${gyroscope.name} / ${gyroscope.vendor} / " +
                        "minDelay=${gyroscope.minDelay}us / maxDelay=${gyroscope.maxDelay}us / " +
                        "fifo=${gyroscope.fifoMaxEventCount}"
            )
        }
        return result
    }

    /**
     * @return [accelerometer]!=null && [gyroscope]!=null
     */
    private fun isSensorExist(): Boolean {
        var result = true
        if (accelerometer == null) {
            Log.e(TAG, "ACCELEROMETER 센서가 존재하지 않음.")
            result = false
        }
        if (gyroscope == null) {
            Log.e(TAG, "GYROSCOPE 센서가 존재하지 않음.")
            result = false
        }
        return result
    }

    /**
     * 센서 이벤트 핸들러를 등록한다.
     *
     * require: [accelerometer]!=null && [gyroscope]!=null
     * @return 등록 성공 여부
     */
    private fun registerListners(): Boolean {
        val accelerometerRegisterResult =
            sensorManager.registerListener(sensorEventListener, accelerometer, SAMPLING_PERIOD_US)
        val gyroscopeRegisterResult =
            sensorManager.registerListener(sensorEventListener, gyroscope, SAMPLING_PERIOD_US)

        var result = true
        if (!accelerometerRegisterResult) {
            Log.e(TAG, "ACCELEROMETER 센서 이벤트 핸들러 등록 실패.")
            result = false
        }
        if (!gyroscopeRegisterResult) {
            Log.e(TAG, "GYROSCOPE 센서 이벤트 핸들러 등록 실패.")
            result = false
        }

        return result
    }

    /**
     * [ImuSampler] 객체를 비활성화한다.
     *
     * ensure: 기존 [queue]를 닫고, 새 큐로 교체한다.
     */
    fun stop() {
        sensorManager.unregisterListener(sensorEventListener)
        _queue.close()
        _queue = Channel()
    }

    /**
     * 현재 센서 수집 현황을 나타내는 [SensorSnapshot] 객체를 만들어 반환한다.
     */
    fun snapshot(): SensorSnapshot {
        return SensorSnapshot(
            accelCount = accelerometerWindow.count,
            accelHz = accelerometerWindow.hz(),
            accelGapExceedCount = accelerometerWindow.gapThresholdExceededCount,
            gyroCount = gyroscopeWindow.count,
            gyroHz = gyroscopeWindow.hz(),
            gyroGapExceedCount = gyroscopeWindow.gapThresholdExceededCount,
            clockDeltaLastNs = clockDelta.last,
            clockDeltaMinNs = clockDelta.min,
            clockDeltaMaxNs = clockDelta.max,
            queueOverflowCount = queueOverflowCount
        )
    }

}