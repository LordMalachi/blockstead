import { forwardRef, type ButtonHTMLAttributes, type PropsWithChildren } from "react";

export const Button = forwardRef<HTMLButtonElement, PropsWithChildren<ButtonHTMLAttributes<HTMLButtonElement>>>(function Button(
  { children, className = "", ...props },
  ref,
) {
  return <button ref={ref} className={`button ${className}`} {...props}>{children}</button>;
});
