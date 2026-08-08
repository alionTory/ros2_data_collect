package io.github.aliontory.imucollect

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
    val sensorSnapshot = _sensorSnapshot.asStateFlow()

    init{
        viewModelScope.launch {
            while(isActive){
                _sensorSnapshot.value = imuSampler.snapshot()
                delay(updatePeriod)
            }
        }
    }
}