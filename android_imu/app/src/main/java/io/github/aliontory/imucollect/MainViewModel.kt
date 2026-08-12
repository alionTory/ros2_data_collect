package io.github.aliontory.imucollect

import android.app.Application
import android.os.SystemClock
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.time.Duration


/**
 * [updatePeriod] 주기로 [imuCaptureAndSendManager]를 읽어 센서 수집 및 전송 정보를 갱신한다.
 */
class MainViewModel(updatePeriod: Duration, application: Application) :
    AndroidViewModel(application) {
    private val imuCaptureAndSendManager: ImuCaptureAndSendManager by lazy {
        ImuCaptureAndSendManager(getApplication())
    }
    private val _imuSamplerSnapshot = MutableStateFlow(ImuSamplerSnapshot())
    private val _imuPacketSenderSnapshot = MutableStateFlow(ImuPacketSenderSnapshot())
    private val _deepSleepTimeMs = MutableStateFlow(0L)
    val imuSamplerSnapshot = _imuSamplerSnapshot.asStateFlow()
    val imuPacketSenderSnapshot = _imuPacketSenderSnapshot.asStateFlow()

    /**
     * 부팅 이후 deep sleep을 한 시간(밀리세컨드)
     */
    val deepSleepTimeMs = _deepSleepTimeMs.asStateFlow()
    val deepSleepTimeMsInitial = SystemClock.elapsedRealtime() - SystemClock.uptimeMillis()

    var host by mutableStateOf("")
        private set

    var port by mutableStateOf("")
        private set

    var portErrorMessage by mutableStateOf<String?>(null)
        private set

    init {
        viewModelScope.launch {
            while (isActive) {
                _imuSamplerSnapshot.value = imuCaptureAndSendManager.imuSamplerSnapshot
                _imuPacketSenderSnapshot.value = imuCaptureAndSendManager.imuPacketSenderSnapshot
                _deepSleepTimeMs.value = SystemClock.elapsedRealtime() - SystemClock.uptimeMillis()
                delay(updatePeriod)
            }
        }
    }

    fun onHostChange(newHost: String) {
        host = newHost
    }

    fun onPortChange(newPort: String) {
        port = newPort
        portErrorMessage = null
    }

    fun onStart() {
        val portInt = port.toIntOrNull()
        if (portInt == null) {
            portErrorMessage = "포트 주소는 정수여야 합니다."
        } else {
            imuCaptureAndSendManager.start(host, portInt)
        }
    }

    fun onStop() {
        imuCaptureAndSendManager.stop()
    }

    fun onResetClockDelta() {
        imuCaptureAndSendManager.resetClockDelta()
    }
}