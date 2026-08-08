package io.github.aliontory.imucollect

/**
 * 한 센서 소스에 대한 데이터 수집을 기록하고, 통계를 제공한다.
 */
class SensorWindow {
    /**
     * 데이터 수집 횟수.
     */
    var count: Long = 0L
        private set

    /**
     * 첫 데이터를 수집한 시각 타임스탬프. 나노세컨드 단위.
     */
    var firstNs: Long = 0L
        private set

    /**
     * 마지막 데이터를 수집한 시각. 나노세컨드 단위
     */
    var lastNs: Long = 0L
        private set

    /**
     * 데이터 수집을 기록한다. 데이터가 수집될 때마다 이 함수를 호출할 것.
     * - ensure: if (old [count] == 0L) [firstNs] == [timestampNs] else true
     * - ensure: [lastNs] == [timestampNs]
     * - ensure: old [count] + 1 == [count]
     * @param timestampNs 현재 데이터 수집 시각 (나노세컨드)
     */
    fun add(timestampNs: Long) {
        if (count == 0L) firstNs = timestampNs
        lastNs = timestampNs
        count += 1
    }

    /**
     * 평균 데이터 수집률(Hz)을 반환한다.
     *
     * [count] < 2 또는 [lastNs] - [firstNs] <= 0 이면 null 반환.
     */
    fun hz(): Double? {
        return if (count < 2)
            null
        else {
            val collectTimeSpanNs = lastNs - firstNs
            if (collectTimeSpanNs <= 0)
                null
            else
                (count - 1) / (collectTimeSpanNs / 1e9)
        }
    }


}