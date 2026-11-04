import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

/** API timestamps are UTC; some arrive without an offset (SQLite), so add one only when it is missing. */
export const parseUtc = (iso: string) => new Date(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : iso + "Z");
