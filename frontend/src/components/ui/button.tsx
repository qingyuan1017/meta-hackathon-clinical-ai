import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "focus-ring inline-flex items-center justify-center gap-2 rounded-lg text-sm font-bold transition disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        default: "bg-zinc-100 px-4 py-2.5 text-zinc-950 shadow-sm hover:bg-white",
        clinical: "bg-clinical-600 px-4 py-2.5 text-white shadow-sm hover:bg-clinical-700",
        outline: "border border-white/15 bg-white/[0.03] px-4 py-2.5 text-zinc-200 hover:bg-white/[0.08]",
        ghost: "px-3 py-2 text-zinc-400 hover:bg-white/[0.06] hover:text-white",
        danger: "border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-rose-300 hover:bg-rose-500/20",
      },
      size: { default: "h-10", sm: "h-8 text-xs", lg: "h-12 px-6" },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> { asChild?: boolean; }

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "button";
  return <Comp className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />;
});
Button.displayName = "Button";
