/**
 * Small text helpers of the evidence card: how a card names its place, its files and its value-conflict cells.
 * Pure functions; the pages and the summary panel share them (and the tests pin them).
 */

/** The location code the pipeline uses for «the whole object» (no room / element). */
export const OBJECT_LOCATION = 'OBJECT';

/** Locations of a card that are real rooms / elements (the whole-object marker is dropped). */
export function placeLocations(locations: readonly string[] | null | undefined): string[] {
  return (locations ?? []).filter((l) => l && l !== OBJECT_LOCATION);
}

/** «пом. 140, 142» / «объект в целом» / «объект в целом; пом. 140» for the side panel. */
export function locationsText(locations: readonly string[] | null | undefined): string {
  const places = placeLocations(locations);
  const whole = (locations ?? []).includes(OBJECT_LOCATION) || (locations ?? []).length === 0;
  const rooms = places.length ? `пом. ${places.join(', ')}` : '';
  if (whole && rooms) return `объект в целом; ${rooms}`;
  return rooms || 'объект в целом';
}

/** The title suffix: «, пом. 140» for rooms, «» for the whole object (the title then has no place at all). */
export function titlePlace(locations: readonly string[] | null | undefined): string {
  const places = placeLocations(locations);
  return places.length ? `, пом. ${places.join(', ')}` : '';
}

/**
 * Short, recognisable name of a document for a tab: the last part of a hyphenated code («…-П-АР 2024.pdf» → «АР 2024»,
 * «…-П-ПБ.pdf» → «ПБ»), otherwise the file name without extension, cut to 26 characters.
 */
export function shortFileName(name: string | null | undefined): string | null {
  if (!name) return null;
  const base = name.replace(/\.[A-Za-z0-9]{2,4}$/u, '').trim();
  if (!base) return null;
  const tail = /-([^-\s][^-]*)$/u.exec(base)?.[1]?.trim();
  const short = tail && tail.length <= 16 ? tail : base;
  return short.length > 26 ? `${short.slice(0, 25)}…` : short;
}

/** Conflicting values of one stage, as the card shows them: «1,7 % (3 файла); 1 % (1 файл)»; «—» when none. */
export function stageValueText(value: string | null | undefined): string {
  return value && value.trim() ? value : '—';
}
