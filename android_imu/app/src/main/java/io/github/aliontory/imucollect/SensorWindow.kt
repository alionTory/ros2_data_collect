package io.github.aliontory.imucollect

/**
 * 한 센서 소스에 대한 데이터 수집을 기록하고, 통계를 제공한다.
 *
 * @param gapThresholdNs 나노세컨드 단위 시간. [add] 호출 시 타임스탬프가 최근 타임스탬프보다 [gapThresholdNs] 를 초과하여 늦은 경우, 센서 수집이 일시 중지되었다 재개된 것으로 간주한다.
 */
class SensorWindow(val gapThresholdNs: Long) {
    /**
     * 하나의 연속된 시간 구간을 표현. 시작 시각, 종료 시각으로 구성된다.
     * @param startTimeNs 시작 시각 나노세컨드
     */
    class TimeSegment(val startTimeNs: Long) {
        /**
         * 종료 시각 나노세컨드.
         *
         * 초기값은 null이며, 이는 종료 시각이 아직 지정되지 않았음을 의미한다.
         */
        var endTimeNs: Long? = null
            private set

        /**
         * 종료 시각을 갱신한다.
         *
         * - ensure: [endTimeNs] == [newEndTimeNs]
         */
        fun update(newEndTimeNs: Long) {
            this.endTimeNs = newEndTimeNs
        }

        /**
         * [endTimeNs]==null 일 경우 0L 반환.
         * 그렇지 않은 경우, 시간 구간의 길이(나노세컨드)를 반환.
         */
        val durationNs: Long
            get() {
                val endTimeNs = endTimeNs  // 이거 없으면 컴파일러가 동시성 어쩌고 하면서 endTimeNs non-null 보장을 안 해줌.
                return if (endTimeNs == null) 0L else (endTimeNs - startTimeNs)
            }
    }

    /**
     * 데이터 수집이 진행 중인 시간 구간을 기록하는 리스트.
     *
     * 데이터 수집 시각 간격이 [gapThresholdNs]를 넘지 않는 범위를 하나의 수집 시간 구간으로 간주한다.
     */
    private val _samplingTimeSegments = mutableListOf<TimeSegment>()

    /**
     * 현재 기록 중인 시간 구간.
     */
    private val _currentTimeSegments: TimeSegment? get() = _samplingTimeSegments.lastOrNull()

    /**
     * 데이터 수집 횟수.
     */
    var count: Long = 0L
        private set

    /**
     * [lastNs] 보다 [gapThresholdNs]를 초과하여 늦게 기록된 타임스탬프의 개수.
     */
    var gapThresholdExceededCount = 0L
        private set


    /**
     * 마지막으로 데이터를 수집한 시각. 나노세컨드 단위
     *
     * 아직 데이터를 수집을 기록한 적이 없는 경우 null 반환.
     * - ensure: [lastNs] != null implies [_currentTimeSegments] != null
     */
    val lastNs: Long?
        get() {
            val currentTimeSegments = _currentTimeSegments

            return if (currentTimeSegments == null)
                null
            else if (currentTimeSegments.endTimeNs == null)
                currentTimeSegments.startTimeNs
            else
                currentTimeSegments.endTimeNs
        }

    /**
     * [startTimeNs]로 시작하는 새로운 수집 구간 기록을 시작한다.
     * 기존 기록 중이던 수집 시간 구간이 있다면 이를 닫는다.
     */
    private fun startNewTimeSegment(startTimeNs: Long) {
        _samplingTimeSegments.add(TimeSegment(startTimeNs))
    }

    /**
     * 기록된 데이터 수집 시각이 직전 시간보다 앞선 횟수.
     */
    var backwardCount = 0L
        private set

    /**
     * 데이터 수집을 기록한다. 데이터가 수집될 때마다 이 함수를 호출할 것.
     *
     * [lastNs] + [gapThresholdNs] < [timestampNs] 인 경우, [lastNs] ~ [timestampNs] 구간 동인 데이터 수집이 중지되었다 재개된 것으로 간주한다.
     *
     * - ensure: [lastNs] == [timestampNs]
     * - ensure: old [count] + 1 == [count]
     * @param timestampNs 현재 데이터 수집 시각 (나노세컨드)
     */
    fun add(timestampNs: Long) {
        val lastNs = this.lastNs
        if (lastNs == null)
            startNewTimeSegment(timestampNs)
        else {
            val currentTimeSegments = this._currentTimeSegments
            check(currentTimeSegments != null)

            if (timestampNs < lastNs) backwardCount += 1
            if (lastNs + gapThresholdNs < timestampNs) {
                startNewTimeSegment(timestampNs)
                gapThresholdExceededCount += 1
            } else
                currentTimeSegments.update(timestampNs)
        }
        count += 1
    }

    /**
     * 평균 데이터 수집률(Hz)을 반환한다.
     *
     * 데이터 수집이 중지되었던 시간 구간은 Hz 계산에서 제외된다:
     *
     * [add]로 추가한 일련의 타임스탬프 시퀀스에서, 인접한 두 시각의 차가 [gapThresholdNs]를 넘지 않는 연속된 범위를 하나의 수집 구간으로 간주한다.
     * [hz]의 리턴 결과는 이러한 각 수집 구간별 주파수의 가중 평균이다.
     * 두 구간 사이의 빈 틈, 즉 [gapThresholdNs]를 초과한 시간 간격은,
     * 데이터 수집이 일시 중지되었다 재개된 것으로 간주하여, 평균 데이터 수집률 계산에서 제외된다.
     * 시각이 하나 뿐인 구간, 즉 양 옆 시각과의 차가 둘 다 [gapThresholdNs]를 넘는 수집 시각도 계산에서 제외된다.
     *
     * 아직 수집 시간 구간이 없는 경우, 즉
     * - [add]가 한 번도 호출되지 않았거나
     * - 타임스탬프 시퀀스 내에, 차가 [gapThresholdNs] 이하인 두 인접한 시각이 하나도 없는 경우
     * 0L을 반환한다.
     */
    fun hz(): Double? {
        val lastNs = this.lastNs
        return if (lastNs == null) {
            0.0
        } else {
            val totalSamplingTimeNs = _samplingTimeSegments.sumOf { it.durationNs }
            if (totalSamplingTimeNs == 0L)
                0.0
            else
                (count - _samplingTimeSegments.count()) / (totalSamplingTimeNs / 1e9)
        }
    }


}