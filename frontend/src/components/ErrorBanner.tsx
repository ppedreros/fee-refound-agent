import { copy } from "../copy/en";

/** A calm banner with the message Luis can read, and a way to try again. */
export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-md border border-error/30 bg-white p-3 text-sm">
      <p className="text-error">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 font-medium text-navy underline underline-offset-2"
        >
          {copy.errors.tryAgain}
        </button>
      )}
    </div>
  );
}
