import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "focus-ring inline-flex items-center justify-center gap-2 rounded-md text-sm font-semibold transition disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        default: "bg-slate-900 px-4 py-2.5 text-white shadow-sm hover:bg-slate-800",
        clinical: "bg-[#173f3b] px-4 py-2.5 text-white shadow-sm hover:bg-[#20574f]",
        outline: "border border-slate-300 bg-white px-4 py-2.5 text-slate-700 hover:bg-slate-50",
        ghost: "px-3 py-2 text-slate-600 hover:bg-slate-100 hover:text-slate-900",
        danger: "border border-rose-300 bg-rose-50 px-3 py-2 text-rose-700 hover:bg-rose-100",
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
