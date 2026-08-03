import { Button } from "./Button";

/** role="alert" so assistive tech announces the failure immediately, unlike
 * the pre-redesign pages which either swallowed errors into an empty state
 * or rendered a silent <p>. Always offers a retry when one is available. */
export function ErrorState({
  message = "No se pudo conectar con el servidor.",
  onRetry,
}: {
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-lg bg-error-container px-6 py-10 text-center text-on-error-container"
    >
      <p className="text-sm font-medium">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Reintentar
        </Button>
      )}
    </div>
  );
}
