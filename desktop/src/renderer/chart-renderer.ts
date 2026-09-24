import { safePlainText } from "./presentation";

const NS = "http://www.w3.org/2000/svg";
const NUMBER = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
type Point = { x: string | number; y: number };
type Chart = { chartType: "bar" | "line" | "scatter"; title: string; xTitle: string; yTitle: string; values: Point[] };

export function renderChartSpec(container: HTMLElement, raw: Record<string, unknown>): void {
  const spec = validateSpec(raw);
  const card = document.createElement("figure");
  card.className = "chart-card";
  card.dataset.chartType = spec.chartType;
  const header = document.createElement("div");
  header.className = "chart-card-header";
  const titleBlock = document.createElement("div");
  const caption = document.createElement("figcaption");
  caption.textContent = spec.title;
  const subtitle = document.createElement("p");
  subtitle.className = "chart-subtitle";
  subtitle.textContent = `${spec.xTitle} · ${spec.yTitle} · ${spec.values.length} 个数据点`;
  titleBlock.append(caption, subtitle);
  const type = document.createElement("span");
  type.className = "chart-type";
  type.textContent = spec.chartType === "bar" ? "分类比较" : spec.chartType === "line" ? "趋势" : "散点";
  header.append(titleBlock, type);

  const visual = document.createElement("div");
  visual.className = "chart-card-visual";
  const tooltip = document.createElement("div");
  tooltip.className = "chart-tooltip";
  tooltip.hidden = true;
  const width = spec.chartType === "bar" ? Math.max(800, spec.values.length * 52) : Math.max(800, spec.values.length * 20);
  const height = 380;
  const left = 76, right = 26, top = 25, bottom = 78;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const minimum = Math.min(0, ...spec.values.map((point) => point.y));
  const maximum = Math.max(0, ...spec.values.map((point) => point.y));
  const step = niceStep((maximum - minimum || 1) / 4);
  const low = Math.floor(minimum / step) * step;
  const high = Math.ceil((maximum || step) / step) * step;
  const yPosition = (value: number): number => top + ((high - value) / (high - low || 1)) * plotHeight;
  const zero = yPosition(0);
  const svg = element("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": spec.title });
  svg.style.setProperty("--chart-min-width", `${width}px`);
  const grid = element("g", {});
  for (let tick = low; tick <= high + step / 10; tick += step) {
    const location = yPosition(tick);
    grid.append(element("line", {
      x1: String(left), y1: String(location), x2: String(width - right), y2: String(location),
      class: Math.abs(tick) < step / 10 ? "zero-line" : "grid-line",
    }));
    const label = element("text", { x: String(left - 12), y: String(location + 4), "text-anchor": "end" });
    label.textContent = NUMBER.format(Math.abs(tick) < step / 10 ? 0 : tick);
    grid.append(label);
  }
  svg.append(grid);
  const xAxis = element("text", { x: String(left + plotWidth / 2), y: String(height - 12), "text-anchor": "middle", class: "axis-title" });
  xAxis.textContent = spec.xTitle;
  const yAxis = element("text", { x: "17", y: String(top + plotHeight / 2), "text-anchor": "middle", transform: `rotate(-90 17 ${top + plotHeight / 2})`, class: "axis-title" });
  yAxis.textContent = spec.yTitle;
  svg.append(xAxis, yAxis);

  const showTooltip = (target: SVGElement, point: Point): void => {
    tooltip.textContent = `${displayX(point.x)} · ${spec.yTitle} ${NUMBER.format(point.y)}`;
    tooltip.hidden = false;
    const targetRect = target.getBoundingClientRect();
    const visualRect = visual.getBoundingClientRect();
    const x = Math.max(8, Math.min(visual.clientWidth - 220, targetRect.left - visualRect.left + targetRect.width / 2));
    tooltip.style.left = `${x + visual.scrollLeft}px`;
    tooltip.style.top = `${Math.max(8, targetRect.top - visualRect.top - 34)}px`;
  };
  const bindMark = (mark: SVGElement, point: Point): void => {
    mark.setAttribute("class", "data-mark");
    mark.setAttribute("tabindex", "0");
    mark.setAttribute("aria-label", `${displayX(point.x)}，${spec.yTitle} ${NUMBER.format(point.y)}`);
    const title = element("title", {});
    title.textContent = `${displayX(point.x)}: ${NUMBER.format(point.y)}`;
    mark.append(title);
    mark.addEventListener("pointerenter", () => showTooltip(mark, point));
    mark.addEventListener("pointerleave", () => { tooltip.hidden = true; });
    mark.addEventListener("focus", () => showTooltip(mark, point));
    mark.addEventListener("blur", () => { tooltip.hidden = true; });
  };
  const xLabel = (x: number, point: Point): void => {
    const label = element("text", { x: String(x), y: String(height - bottom + 22), "text-anchor": "middle" });
    const text = displayX(point.x);
    label.textContent = text.length > 12 ? `${text.slice(0, 11)}…` : text;
    const title = element("title", {});
    title.textContent = text;
    label.append(title);
    svg.append(label);
  };

  if (spec.chartType === "bar") {
    const slot = plotWidth / spec.values.length;
    spec.values.forEach((point, index) => {
      const center = left + slot * (index + .5);
      const targetY = yPosition(point.y);
      const bar = element("rect", {
        x: String(center - Math.min(34, slot * .34)), y: String(Math.min(targetY, zero)),
        width: String(Math.min(68, slot * .68)), height: String(Math.max(1, Math.abs(zero - targetY))),
        fill: "#24716a", rx: "3",
      });
      bindMark(bar, point);
      svg.append(bar);
      if (spec.values.length <= 20 || index % Math.ceil(spec.values.length / 20) === 0) xLabel(center, point);
    });
  } else if (spec.chartType === "line") {
    const stepX = plotWidth / Math.max(1, spec.values.length - 1);
    const positions = spec.values.map((point, index) => [left + stepX * index, yPosition(point.y)] as const);
    const path = element("polyline", {
      points: positions.map(([x, y]) => `${x},${y}`).join(" "), fill: "none",
      stroke: "#24716a", "stroke-width": "3", "stroke-linecap": "round", "stroke-linejoin": "round",
    });
    svg.append(path);
    spec.values.forEach((point, index) => {
      const [x, y] = positions[index];
      const dot = element("circle", { cx: String(x), cy: String(y), r: "5", fill: "#fff", stroke: "#24716a", "stroke-width": "2.5" });
      bindMark(dot, point);
      svg.append(dot);
      if (spec.values.length <= 12 || index % Math.ceil(spec.values.length / 12) === 0) xLabel(x, point);
    });
  } else {
    const xs = spec.values.map((point) => Number(point.x));
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const span = maxX - minX || 1;
    spec.values.forEach((point, index) => {
      const circle = element("circle", {
        cx: String(left + ((xs[index] - minX) / span) * plotWidth), cy: String(yPosition(point.y)),
        r: "5", fill: "#24716a", "fill-opacity": ".84",
      });
      bindMark(circle, point);
      svg.append(circle);
    });
    for (let index = 0; index <= 4; index += 1) {
      const label = element("text", { x: String(left + plotWidth * index / 4), y: String(height - bottom + 22), "text-anchor": "middle" });
      label.textContent = NUMBER.format(minX + span * index / 4);
      svg.append(label);
    }
  }
  visual.append(svg, tooltip);

  const details = document.createElement("details");
  details.className = "chart-data-details";
  const detailsTitle = document.createElement("summary");
  detailsTitle.textContent = "查看图表数据";
  const table = document.createElement("table");
  const heading = document.createElement("tr");
  for (const label of [spec.xTitle, spec.yTitle]) {
    const cell = document.createElement("th");
    cell.textContent = label;
    heading.append(cell);
  }
  table.append(heading);
  for (const point of spec.values) {
    const row = document.createElement("tr");
    for (const value of [displayX(point.x), NUMBER.format(point.y)]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    table.append(row);
  }
  details.append(detailsTitle, table);
  card.append(header, visual, details);
  container.append(card);
}

function validateSpec(raw: Record<string, unknown>): Chart {
  const chartType = raw.chartType;
  const data = raw.data;
  const values = isRecord(data) ? data.values : null;
  if (!([ "bar", "line", "scatter" ] as unknown[]).includes(chartType) || typeof raw.title !== "string" || !Array.isArray(values) || values.length === 0 || values.length > 100) {
    throw new Error("Invalid Chart Spec");
  }
  const points = values.map((item) => {
    if (!isRecord(item) || (typeof item.x !== "string" && typeof item.x !== "number") || typeof item.y !== "number" || !Number.isFinite(item.y)) {
      throw new Error("Invalid Chart Spec point");
    }
    return { x: item.x, y: item.y };
  });
  if (chartType === "scatter" && points.some((point) => !Number.isFinite(Number(point.x)))) throw new Error("Invalid scatter Chart Spec");
  const encoding = isRecord(raw.encoding) ? raw.encoding : {};
  const x = isRecord(encoding.x) ? encoding.x : {};
  const y = isRecord(encoding.y) ? encoding.y : {};
  return {
    chartType: chartType as Chart["chartType"],
    title: safePlainText(raw.title) ?? "分析图表",
    xTitle: typeof x.title === "string" ? safePlainText(x.title) ?? "分类" : "分类",
    yTitle: typeof y.title === "string" ? safePlainText(y.title) ?? "数值" : "数值",
    values: points,
  };
}

function niceStep(raw: number): number {
  const power = 10 ** Math.floor(Math.log10(raw || 1));
  const scaled = raw / power;
  return (scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10) * power;
}

function displayX(value: string | number): string {
  return safePlainText(String(value)) ?? "未命名分类";
}

function element(name: string, attributes: Record<string, string>): SVGElement {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
