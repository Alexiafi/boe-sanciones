/**
 * Purely indicative age tiers for the "Historial" screen — NOT a legal
 * prescription/statute-of-limitations calculation (real limitation periods
 * depend on the specific infracción and are outside this tool's scope; see
 * docs/LIMITES.md). Two things are parametrised here and documented, not
 * invented as fact:
 *  - the TEU public-search window is 90 days (services/historico/teu_publico.py's
 *    TEU_VENTANA_PUBLICA_DIAS, mirrored here for the UI tier only);
 *  - the "reciente"/"archivado" cutoffs are illustrative defaults a future
 *    session can make configurable once Judit defines what she actually
 *    wants tracked.
 */
export type PrescripcionTier = "urgente" | "proximo" | "reciente" | "archivado";

const TEU_VENTANA_DIAS = 90;
const RECIENTE_DIAS = 180;
const ARCHIVADO_DIAS = 365 * 4;

export function prescripcionTier(fechaPublicacion: string, fuente: string): PrescripcionTier {
  const dias = Math.floor((Date.now() - new Date(fechaPublicacion).getTime()) / 86_400_000);

  if (fuente === "teu") {
    if (dias >= TEU_VENTANA_DIAS - 15) return "urgente";
    if (dias >= TEU_VENTANA_DIAS - 30) return "proximo";
  }
  if (dias > ARCHIVADO_DIAS) return "archivado";
  if (dias > RECIENTE_DIAS) return "proximo";
  return "reciente";
}
