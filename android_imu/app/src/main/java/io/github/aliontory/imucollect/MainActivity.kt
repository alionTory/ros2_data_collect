package io.github.aliontory.imucollect

import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import io.github.aliontory.imucollect.ui.theme.ImuCollectTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import kotlin.time.Duration
import kotlin.time.Duration.Companion.nanoseconds
import kotlin.time.Duration.Companion.seconds

private const val TAG = "MainActivity"

class MainActivity : ComponentActivity() {
    private lateinit var imuSampler: ImuSampler

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        imuSampler = ImuSampler(this)
        enableEdgeToEdge()
        setContent {
            ImuMenu(imuSampler)
        }
    }

    override fun onResume() {
        super.onResume()
        imuSampler.start()
    }

    override fun onPause() {
        super.onPause()
        imuSampler.stop()
    }
}

@Composable
fun ImuMenu(
    imuSampler: ImuSampler,
    updatePeriod: Duration = 1.seconds,
    sensorSnapshotViewModel: SensorSnapshotViewModel = viewModel(
        factory = viewModelFactory {
            initializer {
                SensorSnapshotViewModel(imuSampler, updatePeriod)
            }
        }
    )
) {
    ImuCollectTheme {
        Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
            Column(modifier = Modifier.padding(innerPadding)) {
                SensorSnapshotMenu(sensorSnapshotViewModel)
                UdpSendMenu()
            }
        }
    }
}

@Composable
fun SensorSnapshotMenu(sensorSnapshotViewModel: SensorSnapshotViewModel, modifier: Modifier = Modifier) {
    Column(modifier = modifier.padding(16.dp)){
        val sensorSnapshot by sensorSnapshotViewModel.sensorSnapshot.collectAsStateWithLifecycle()
        Text(String.format("가속도 - 요청 %dHz, 실측 %.6fHz, 표본 수 %d", ImuSampler.SAMPLING_RATE_HZ, sensorSnapshot.accelHz, sensorSnapshot.accelCount))
        Text(String.format("자이로 - 요청 %dHz, 실측 %.6fHz, 표본 수 %d", ImuSampler.SAMPLING_RATE_HZ, sensorSnapshot.gyroHz, sensorSnapshot.gyroCount))
        Text(String.format("클럭 차이 - 최근 %dms, 최소 %dms, 최대 %dms", sensorSnapshot.clockDeltaLastNs.nanoseconds.inWholeMilliseconds, sensorSnapshot.clockDeltaMinNs.nanoseconds.inWholeMilliseconds, sensorSnapshot.clockDeltaMaxNs.nanoseconds.inWholeMilliseconds))
    }
}


@Composable
fun UdpSendMenu(modifier: Modifier = Modifier) {
    Column(modifier = modifier.padding(16.dp)) {
        val ipAddressState = rememberTextFieldState()
        TextField(state = ipAddressState, label = { Text("IP 주소") })

        val portState = rememberTextFieldState()
        var errorMessage by remember { mutableStateOf<String?>(null) }
        TextField(
            state = portState,
            isError = errorMessage != null,
            supportingText = {
                errorMessage?.let {
                    Text(
                        it,
                        color = MaterialTheme.colorScheme.error
                    )
                }
            },
            label = { Text("포트 주소") })

        val scope = rememberCoroutineScope()
        Button(onClick = {
            val port = portState.text.toString().toIntOrNull()
            if (port == null) {
                errorMessage = "포트 주소는 정수여야 합니다."
            } else {
                errorMessage = null
                scope.launch {
                    sendUdpMessage(ipAddressState.text.toString(), port, "Hello.")
                }
            }

        }) {
            Text("UDP 전송")
        }
    }
}

suspend fun sendUdpMessage(address: String, port: Int, text: String) {
    withContext(Dispatchers.IO) {
        Log.i(TAG, "UDP 전송 시작. 주소 $address, 포트 $port.")
        DatagramSocket().use { socket ->
            val data = text.toByteArray()
            val inetAddress = InetAddress.getByName(address)
            val packet = DatagramPacket(data, data.size, inetAddress, port)
            socket.send(packet)
        }
        Log.i(TAG, "UDP 전송 완료.")
    }

}