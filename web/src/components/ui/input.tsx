import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn("h-12 w-full rounded-md border bg-card px-4 text-base placeholder:text-muted-foreground disabled:opacity-50", className)}
    {...props}
  />
));
Input.displayName = "Input";
