import { cn } from "@/lib/utils";

interface SpinnerProps {
  className?: string;
  /** Defaults to "w-4 h-4" */
  size?: "sm" | "md" | "lg";
}

const SIZE_CLASSES = {
  sm: "w-3 h-3",
  md: "w-4 h-4",
  lg: "w-5 h-5",
};

export function Spinner({ className, size = "md" }: SpinnerProps) {
  return (
    <svg
      className={cn("animate-spin", SIZE_CLASSES[size], className)}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}
