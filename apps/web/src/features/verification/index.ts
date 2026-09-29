/**
 * Verification feature (AG-05). Routes to add in App.tsx (AG-08), lazily like the other features:
 *   <Route path="verification" element={<Lazy><VerificationPage /></Lazy>} />
 *   <Route path="verification/:processId" element={<Lazy><VerificationPage /></Lazy>} />
 *   <Route path="verification/:processId/:findingId" element={<Lazy><VerificationPage /></Lazy>} />
 *   <Route path="objects/:objectId/verify" element={<Lazy><VerificationPage /></Lazy>} />
 * The evidence viewer is AG-08's EvidenceViewer ({card: EvidenceCard, group: FindingGroup}), imported as is.
 */
export { VerificationPage, verificationPath } from './VerificationPage';
export { Workspace } from './Workspace';
