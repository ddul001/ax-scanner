import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const variants = cva(
  "inline-flex items-center gap-1 rounded px-2 py-0.5 font-mono text-[11px] font-medium uppercase tracking-wide",
  {
    variants: {
      tone: {
        neutral: "bg-muted text-muted-foreground",
        outline: "border text-muted-foreground",
        primary: "border border-primary/40 bg-primary/10 text-primary",
        ok: "bg-ok/12 text-ok",
        warn: "bg-warn/12 text-warn",
        fail: "bg-fail/12 text-fail",
        dashed: "border border-dashed text-muted-foreground",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);
export const Badge = ({ className, tone, ...props }: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof variants>) => (
  <span className={cn(variants({ tone }), className)} {...props} />
);
