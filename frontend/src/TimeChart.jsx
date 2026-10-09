import React, { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkAreaComponent,
  LegendComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkAreaComponent,
  LegendComponent,
  CanvasRenderer,
]);
const date = (ts) =>
  new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(ts));
export default function TimeChart({ series, status, bounds, unit, color }) {
  const element = useRef(null),
    instance = useRef(null);
  useEffect(() => {
    instance.current = echarts.init(element.current, null, {
      renderer: "canvas",
    });
    const resize = new ResizeObserver(() => instance.current?.resize());
    resize.observe(element.current);
    return () => {
      resize.disconnect();
      instance.current.dispose();
      instance.current = null;
    };
  }, []);
  useEffect(() => {
    const offline = [];
    let begin = null;
    const points = status[0]?.points || [];
    points.forEach(([ts, value], i) => {
      if (value === 0 && begin === null) begin = ts * 1000;
      if (begin !== null && (value !== 0 || i === points.length - 1)) {
        offline.push([{ xAxis: begin }, { xAxis: ts * 1000 }]);
        begin = null;
      }
    });
    const curves = series.map((s, i) => ({
      name: s.label === "tcp" ? `TCP` : s.label,
      type: "line",
      showSymbol: false,
      connectNulls: false,
      sampling: "lttb",
      lineStyle: { width: 1.6 },
      itemStyle: {
        color: i === 0 ? color : ["#75b7ad", "#a18ec9", "#d1a568"][i % 3],
      },
      data: s.points.map(([ts, value]) => [ts * 1000, value]),
      markArea:
        i === 0
          ? {
              silent: true,
              itemStyle: { color: "rgba(210,83,83,0.09)" },
              data: offline,
            }
          : undefined,
    }));
    if (!curves.length)
      curves.push({
        type: "line",
        data: [],
        markArea: {
          silent: true,
          itemStyle: { color: "rgba(210,83,83,0.09)" },
          data: offline,
        },
      });
    instance.current.setOption(
      {
        animation: false,
        backgroundColor: "transparent",
        textStyle: { color: "#858d9c", fontFamily: "system-ui" },
        grid: {
          top: series.length > 1 ? 36 : 18,
          right: 15,
          bottom: 54,
          left: 48,
        },
        tooltip: {
          trigger: "axis",
          backgroundColor: "#191e27",
          borderColor: "#303744",
          textStyle: { color: "#e1e6ef", fontSize: 12 },
          confine: true,
          formatter: (params) => {
            const lines = [date(params[0]?.value?.[0] || 0)];
            for (const p of params) {
              const value = p.value?.[1];
              const label = String(p.seriesName).replace(
                /[&<>"']/g,
                (c) =>
                  ({
                    "&": "&amp;",
                    "<": "&lt;",
                    ">": "&gt;",
                    '"': "&quot;",
                    "'": "&#39;",
                  })[c],
              );
              lines.push(
                `${p.marker} ${label}: ${value == null ? "—" : Number(value).toFixed(2) + " " + unit}`,
              );
            }
            return lines.join("<br/>");
          },
        },
        legend: {
          show: series.length > 1,
          top: 0,
          type: "scroll",
          textStyle: { color: "#8f97a6", fontSize: 10 },
        },
        xAxis: {
          type: "time",
          min: bounds?.start * 1000,
          max: bounds?.end * 1000,
          axisLine: { lineStyle: { color: "#262c35" } },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: {
            fontSize: 10,
            hideOverlap: true,
            formatter: (ts) =>
              new Intl.DateTimeFormat("zh-CN", {
                timeZone: "Asia/Shanghai",
                hour: "2-digit",
                minute: "2-digit",
                hour12: false,
              }).format(new Date(ts)),
          },
        },
        yAxis: {
          type: "value",
          min: 0,
          axisLabel: { fontSize: 10 },
          splitLine: { lineStyle: { color: "#1e232c" } },
          axisLine: { show: false },
        },
        dataZoom: [
          {
            type: "inside",
            zoomOnMouseWheel: "ctrl",
            moveOnMouseMove: true,
            preventDefaultMouseMove: true,
          },
          {
            type: "slider",
            height: 12,
            bottom: 9,
            borderColor: "#262c35",
            backgroundColor: "#11151b",
            fillerColor: "rgba(100,155,220,0.09)",
            handleStyle: { color: "#687689" },
            showDetail: false,
          },
        ],
        series: curves,
      },
      { notMerge: true },
    );
  }, [series, status, bounds, unit, color]);
  const hasData = series.some((s) => s.points.some((p) => p[1] != null));
  return (
    <div className="chart-container">
      <div
        ref={element}
        className="chart"
        role="img"
        aria-label={`${unit} 时间序列图`}
      />
      {!hasData && (
        <div className="chart-no-data">No samples in this range</div>
      )}
    </div>
  );
}
