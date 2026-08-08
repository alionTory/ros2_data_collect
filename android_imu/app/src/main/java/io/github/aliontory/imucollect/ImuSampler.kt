package io.github.aliontory.imucollect

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.util.Log

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
     * 자이로스코프 센서 데이터 수집 횟수.
     */
    val gyroCount: Long = 0L,
    /**
     * 자이로스코프 센서 데이터 수집율(Hz).
     */
    val gyroHz: Double? = null,
)

class ImuSampler(context: Context) {
    companion object {
        private const val TAG = "ImuSampler"

        /** 20,000μs = 50Hz. 요청값이며 보장이 아니다. */
        const val SAMPLING_PERIOD_US = 20_000
        const val SAMPLING_RATE_HZ = 1e6.toInt() / SAMPLING_PERIOD_US
    }

    private val sensorManager =
        context.getSystemService(Context.SENSOR_SERVICE) as SensorManager

    private val accelerometer: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val gyroscope: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)

    private var accelerometerWindow = SensorWindow()
    private var gyroscopeWindow = SensorWindow()

    private val sensorEventListener = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            when(event.sensor.type){
                Sensor.TYPE_ACCELEROMETER -> accelerometerWindow.add(event.timestamp)
                Sensor.TYPE_GYROSCOPE -> gyroscopeWindow.add(event.timestamp)
                else -> error("예상치 못한 센서 타입: ${event.sensor.type}. 이름: ${event.sensor.name}")
            }
        }

        override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) {
            Log.i(TAG, "센서 ${sensor?.name}의 accurcy가 $accuracy 로 변경됨.")
        }
    }

    /**
     * [ImuSampler] 객체를 활성화한다.
     * @return 활성화에 성공했으면 true */
    fun start(): Boolean {
        val result = isSensorExist() && registerListners();
        if(result) Log.i(TAG, "${ImuSampler::class.simpleName} 객체 활성화 성공")
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
     */
    fun stop() {
        sensorManager.unregisterListener(sensorEventListener)
    }

    /**
     * 현재 센서 수집 현황을 나타내는 [SensorSnapshot] 객체를 만들어 반환한다.
     */
    fun snapshot(): SensorSnapshot{
        return SensorSnapshot(
            accelCount = accelerometerWindow.count,
            accelHz = accelerometerWindow.hz(),
            gyroCount = gyroscopeWindow.count,
            gyroHz = gyroscopeWindow.hz()
        )
    }

}