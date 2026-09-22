const NS = "http://www.w3.org/2000/svg";

type Point = { x: string | number; y: number };

export function renderChartSpec(container: HTMLElement, raw: Record<string, unknown>): void {
  const spec = validateSpec(raw);
  const width = 800;
  const height = 420;
  const left = 64;
  const right = 24;
  const top = 52;
  const bottom = 64;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const values = spec.values;
  const minimum = Math.min(0, ...values.map((item) => item.y));
  let maximum = Math.max(0, ...values.map((item) => item.y));
  if (maximum === minimum) maximum = minimum + 1;
  const y = (value: number): number => top + ((maximum - value) * plotHeight) / (maximum - minimum);
  const baseline = y(0);
  const svg = element("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": spec.title });
  svg.append(element("rect", { width: "100%", height: "100%", fill: "white" }));
  const title = element("text", { x: String(width / 2), y: "30", "text-anchor": "middle" });
  title.textContent = spec.title;
  svg.append(title);
  svg.append(element("line", { x1: String(left), y1: String(top), x2: String(left), y2: String(height - bottom), stroke: "#475569" }));
  svg.append(element("line", { x1: String(left), y1: String(baseline), x2: String(width - right), y2: String(baseline), stroke: "#475569" }));

  if (spec.chartType === "bar") {
    const slot = plotWidth / values.length;
    values.forEach((point, index) => {
      const valueY = y(point.y);
      const rect = element("rect", {
        x: String(left + slot * index + slot * 0.14),
        y: String(Math.min(valueY, baseline)),
        width: String(slot * 0.72),
        height: String(Math.max(1, Math.abs(baseline - valueY))),
        fill: "#2563eb",
      });
      rect.append(titleNode(`${String(point.x)}: ${point.y}`));
      svg.append(rect);
    });
  } else if (spec.chartType === "line") {
    const step = plotWidth / Math.max(1, values.length - 1);
    const points = values.map((point, index) => `${left + step * index},${y(point.y)}`).join(" ");
    svg.append(element("polyline", { points, fill: "none", stroke: "#2563eb", "stroke-width": "2.5" }));
  } else {
    const numericX = values.map((point) => Number(point.x));
    const minX = Math.min(...numericX);
    const maxX = Math.max(...numericX);
    const span = maxX === minX ? 1 : maxX - minX;
    values.forEach((point, index) => {
      const circle = element("circle", {
        cx: String(left + ((numericX[index] - minX) * plotWidth) / span),
        cy: String(y(point.y)),
        r: "4",
        fill: "#2563eb",
      });
      circle.append(titleNode(`${point.x}: ${point.y}`));
      svg.append(circle);
    });
  }
  container.append(svg);
}

function validateSpec(raw: Record<string, unknown>): { chartType: "bar" | "line" | "scatter"; title: string; values: Point[] } {
  const chartType = raw.chartType;
  const data = raw.data;
  const values = isRecord(data) ? data.values : null;
  if (!(["bar", "line", "scatter"] as unknown[]).includes(chartType) || typeof raw.title !== "string" || !Array.isArray(values) || values.length === 0 || values.length > 100) {
    throw new Error("Invalid Chart Spec");
  }
  const points = values.map((value) => {
    if (!isRecord(value) || (typeof value.x !== "string" && typeof value.x !== "number") || typeof value.y !== "number" || !Number.isFinite(value.y)) {
      throw new Error("Invalid Chart Spec point");
    }
    return { x: value.x, y: value.y };
  });
  return { chartType: chartType as "bar" | "line" | "scatter", title: raw.title, values: points };
}

function element(name: string, attributes: Record<string, string>): SVGElement {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

function titleNode(text: string): SVGElement {
  const node = element("title", {});
  node.textContent = text;
  return node;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
