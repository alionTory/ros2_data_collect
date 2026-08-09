package io.github.aliontory.imucollect

import android.os.SystemClock
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.time.Duration


/**
 * [updatePeriod] 주기로 [imuSampler]를 읽어 [sensorSnapshot]을 갱신한다.
 */
class SensorSnapshotViewModel(imuSampler: ImuSampler, updatePeriod: Duration): ViewModel() {
    private val _sensorSnapshot = MutableStateFlow(SensorSnapshot())
    private val _deepSleepTimeMs = MutableStateFlow(0L)
    val sensorSnapshot = _sensorSnapshot.asStateFlow()

    /**
     * 부팅 이후 deep sleep을 한 시간(밀리세컨드)
     */
    val deepSleepTimeMs = _deepSleepTimeMs.asStateFlow()
    val deepSleepTimeMsInitial = SystemClock.elapsedRealtime() - SystemClock.uptimeMillis()

    init{
        viewModelScope.launch {
            while(isActive){
                _sensorSnapshot.value = imuSampler.snapshot()
                _deepSleepTimeMs.value = SystemClock.elapsedRealtime() - SystemClock.uptimeMillis()
                delay(updatePeriod)
            }
        }
    }
}