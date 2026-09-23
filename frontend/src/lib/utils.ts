import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"] as const

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return "0 B"
  if (bytes === 0) return "0 B"
  const negative = bytes < 0
  const abs = Math.abs(bytes)
  const k = 1024
  // Clamp the index: a library over 1 TB used to fall off the end of the unit
  // array and render as "1.2 undefined".
  const i = Math.min(Math.floor(Math.log(abs) / Math.log(k)), BYTE_UNITS.length - 1)
  const value = parseFloat((abs / Math.pow(k, i)).toFixed(2))
  return `${negative ? "-" : ""}${value} ${BYTE_UNITS[i]}`
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "--:--"
  // Durations arrive as floats from ffprobe; without flooring, a value like
  // 125.6 rendered as "2:5.599999999999994".
  const total = Math.max(0, Math.floor(seconds))
  const hrs = Math.floor(total / 3600)
  const mins = Math.floor((total % 3600) / 60)
  const secs = total % 60
  if (hrs > 0) {
    return `${hrs}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`
  }
  return `${mins}:${secs.toString().padStart(2, "0")}`
}

export function formatDate(date: string | Date | null | undefined, timeZone = "UTC"): string {
  if (!date) return "--"
  let input = date
  if (typeof input === "string") {
    // Backend stores naive UTC datetimes; JS treats "2024-01-01T12:00:00" as
    // local time. Append Z so it is parsed as UTC before converting to the
    // target timezone.
    if (!input.endsWith("Z") && !/[-+]\d{2}:\d{2}$/.test(input)) {
      input = input + "Z"
    }
  }
  const d = new Date(input)
  return d.toLocaleDateString("en-US", {
    timeZone,
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}
