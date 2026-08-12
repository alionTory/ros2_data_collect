package io.github.aliontory.imucollect

import android.app.Application
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.lifecycle.ViewModelProvider.AndroidViewModelFactory.Companion.APPLICATION_KEY
import io.github.aliontory.imucollect.ui.theme.ImuCollectTheme
import java.util.Locale
import kotlin.time.Duration.Companion.nanoseconds
import kotlin.time.Duration.Companion.seconds

//private const val TAG = "MainActivity"

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels {
        viewModelFactory {
            initializer {
                val application = (this[APPLICATION_KEY] as Application)
                MainViewModel(1.seconds, application)
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            ImuMenu(viewModel)
        }
    }

    override fun onResume() {
        super.onResume()
    }

    override fun onPause() {
        super.onPause()
        viewModel.onStop()
    }
}

@Composable
fun ImuMenu(mainViewModel: MainViewModel) {
    ImuCollectTheme {
        Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
            Column(modifier = Modifier.padding(innerPadding)) {
                CaptureAndSendStartMenu(mainViewModel)
                SensorSnapshotMenu(mainViewModel)
            }
        }
    }
}

@Composable
fun SensorSnapshotMenu(mainViewModel: MainViewModel, modifier: Modifier = Modifier) {
    Column(modifier = modifier.padding(16.dp)) {
        val imuSamplerSnapshot by mainViewModel.imuSamplerSnapshot.collectAsStateWithLifecycle()
        Text(
            String.format(
                Locale.US,
                "가속도 - 요청 %dHz, 실측 %.6fHz, 표본 수 %d, 수집 간격 초과 %d",
                ImuSampler.SAMPLING_RATE_HZ,
                imuSamplerSnapshot.accelHz,
                imuSamplerSnapshot.accelCount,
                imuSamplerSnapshot.accelGapExceedCount
            )
        )
        Text(
            String.format(
                Locale.US,
                "자이로 - 요청 %dHz, 실측 %.6fHz, 표본 수 %d, 수집 간격 초과 %d",
                ImuSampler.SAMPLING_RATE_HZ,
                imuSamplerSnapshot.gyroHz,
                imuSamplerSnapshot.gyroCount,
                imuSamplerSnapshot.gyroGapExceedCount
            )
        )
        Text(
            String.format(
                Locale.US,
                "클럭 차이 - 최근 %dms, 최소 %dms, 최대 %dms",
                imuSamplerSnapshot.clockDeltaLastNs.nanoseconds.inWholeMilliseconds,
                imuSamplerSnapshot.clockDeltaMinNs.nanoseconds.inWholeMilliseconds,
                imuSamplerSnapshot.clockDeltaMaxNs.nanoseconds.inWholeMilliseconds
            )
        )
        Text("수집 큐 오버플로: ${imuSamplerSnapshot.queueOverflowCount}")

        Text("Deep Sleep 시간 - 초기 ${mainViewModel.deepSleepTimeMsInitial}ms, 현재 ${mainViewModel.deepSleepTimeMs.collectAsStateWithLifecycle().value}ms")

        val imuPacketSenderSnapshot by mainViewModel.imuPacketSenderSnapshot.collectAsStateWithLifecycle()
        Text("가속도 전송 수: ${imuPacketSenderSnapshot.accelSentCount}, 자이로 전송 수: ${imuPacketSenderSnapshot.gyroSentCount}")
        Text("소켓 에러 수: ${imuPacketSenderSnapshot.sendErrorCount}, 최근 에러 메시지: ${imuPacketSenderSnapshot.lastSendErrorMessage}")

        Button(onClick = mainViewModel::onResetClockDelta) {
            Text("클럭 차이 초기화")
        }
    }
}


@Composable
fun CaptureAndSendStartMenu(mainViewModel: MainViewModel, modifier: Modifier = Modifier) {
    Column(modifier = modifier.padding(16.dp)) {
        TextField(
            value = mainViewModel.host,
            onValueChange = mainViewModel::onHostChange,
            label = { Text("IP 주소") })

        TextField(
            value = mainViewModel.port,
            onValueChange = mainViewModel::onPortChange,
            isError = mainViewModel.portErrorMessage != null,
            supportingText = {
                mainViewModel.portErrorMessage?.let {
                    Text(
                        it,
                        color = MaterialTheme.colorScheme.error
                    )
                }
            },
            label = { Text("포트 주소") })

        Row(modifier = modifier.padding(16.dp)) {
            Button(onClick = mainViewModel::onStart) {
                Text("수집/전송 시작")
            }

            Button(onClick = mainViewModel::onStop) {
                Text("수집/전송 중지")
            }
        }
    }
}