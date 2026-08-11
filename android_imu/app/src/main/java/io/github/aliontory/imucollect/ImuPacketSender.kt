package io.github.aliontory.imucollect

import android.util.Log
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.ReceiveChannel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.concurrent.atomic.AtomicLongArray
import kotlin.time.Duration

/**
 * 큐에 쌓인 [ImuSample] 을 UDP 로 전송한다.
 */
class ImuPacketSender(
    val host: String,
    val port: Int,
    val queue: ReceiveChannel<ImuSample>
) {
    companion object {
        private const val TAG = "ImuPacketSender"
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var job: Job? = null

    private var socket: DatagramSocket = DatagramSocket()
    private var address: InetAddress? = null

    /** 센서 데이터 종류별 독립 시퀀스 부여 용도. */
    private val nextSeq = object {
        private val seqArray = AtomicLongArray(MessageType.entries.size)
        operator fun get(key: MessageType): Long = seqArray[key.ordinal]
        operator fun set(key: MessageType, value: Long) {
            seqArray[key.ordinal] = value
        }
    }

    /**
     * 소켓 에러로 전송에 실패한 횟수
     */
    @Volatile
    var sendErrorCount = 0L
        private set

    @Volatile
    var lastSendErrorMessage: String? = null
        private set

    /**
     * 센서별 전송 시도 수를 반환.
     */
    fun sentCount(messageType: MessageType): Long = nextSeq[messageType]
    // nextSeq와 같은 값이지만, 읽기 전용으로 노출된다.

    var started = false
        private set
    var stopped = false
        private set

    /**
     * 주어진 [host], [port] 정보로 UDP 소켓을 만들고,
     * 코루틴을 통해 큐에 저장된 [ImuSample]을 지속적으로 전송한다.
     *
     * require: !started
     * ensure: started
     */
    fun start() {
        require(!started)
        started = true

        job = scope.launch {
            address = InetAddress.getByName(host)
            if (address == null) {
                Log.e(TAG, "주소 host: $host 가 올바르지 않음.")
            } else {
                try {
                    for (sample in queue) sendOne(sample)
                } catch (e: CancellationException) {
                    Log.i(TAG, "타임아웃으로 인해 IMU 전송 작업이 중단됨. 큐를 전부 비우지 못했을 수 있음.")
                }
            }
        }
    }

    /**
     * [sample]을 UDP로 전송한다.
     *
     * require: [address] != null
     */
    private fun sendOne(sample: ImuSample) {
        val address = this.address
        require(address != null)

        try {
            val byteArray = sample.encode(nextSeq[sample.messageType])
            val packet = DatagramPacket(byteArray, byteArray.size, address, port)
            socket.send(packet)
            // seq 번호는 소켓 예외가 아닌 전송 유실을 파악하기 위한 것이므로, 소켓 에러 시엔 seq를 올리지 않는다.
            nextSeq[sample.messageType] += 1
        } catch (e: Exception) {
            sendErrorCount += 1
            lastSendErrorMessage = "${e::class.simpleName}: ${e.message}"
            Log.e(TAG, "전송 실패 (${sendErrorCount}회째)", e)
        }
    }

    /**
     * [timeout] 후에 [ImuSample] 전송 작업을 중단한다.
     *
     * [queue]가 닫힌 상태이고, [timeout] 이전에 큐에 남은 데이터를 전부 전송하는 데 성공한다면, [timeout]이 지나기 전에 전송 작업이 일찍 중단된다.
     *
     * require: started
     * require: !stopped
     * ensure: stopped
     */
    suspend fun stop(timeout: Duration) {
        require(started)
        require(!stopped)
        stopped = true

        val job = this.job
        check(job!=null)

        val jobCompleted = withTimeoutOrNull(timeout){
            job.join()
        }

        if(jobCompleted==null){
            job.cancel()
            job.join()
        }
        socket.close()
    }
}