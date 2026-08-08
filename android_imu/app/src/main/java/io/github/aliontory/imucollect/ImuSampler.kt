package io.github.aliontory.imucollect

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.SystemClock
import android.util.Log

/** UI 표시용 읽기 전용 묶음. 1초에 한 번 만들어진다. */
data class SensorSnapshot(
    val accelCount: Long = 0L,
    val accelHz: Double? = null,
    val gyroCount: Long = 0L,
    val gyroHz: Double? = null,
    val clockDeltaLastNs: Long = 0L,
    val clockDeltaMinNs: Long = 0L,
    val clockDeltaMaxNs: Long = 0L,
)

class ImuSampler(context: Context) {
    companion object {
        private const val TAG = "ImuSampler"

        /** 20,000μs = 50Hz. 요청값이며 보장이 아니다. */
        const val SAMPLING_PERIOD_US = 20_000
    }

    private val sensorManager =
        context.getSystemService(Context.SENSOR_SERVICE) as SensorManager

    private val accelerometer: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val gyroscope: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)

    private val sensorEventListener = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            Log.d(TAG, "센서 수집됨. 센서=${event.sensor?.name}, 타임스탬프=${event.timestamp} 값=${event.values.contentToString()}")
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

}