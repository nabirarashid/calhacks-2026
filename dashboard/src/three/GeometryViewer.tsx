import { ContactShadows, OrbitControls } from '@react-three/drei';
import { Canvas } from '@react-three/fiber';
import type { GeometryRef } from '@shared/contracts';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { BufferGeometry } from 'three';
import { Vector3 } from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';

type ViewerState = 'empty' | 'pending' | 'loading' | 'ready' | 'failed';

export function geometryViewerState(geometry?: GeometryRef | null): ViewerState {
  if (!geometry) return 'empty';
  if (geometry.status === 'failed' || geometry.status === 'skipped') return 'failed';
  if (geometry.status !== 'ready') return 'pending';
  return geometry.stl_url ? 'loading' : 'failed';
}

function LoadedStl({
  url,
  onState,
}: {
  url: string;
  onState: (state: ViewerState, error?: string) => void;
}) {
  const [mesh, setMesh] = useState<BufferGeometry | null>(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    let cancelled = false;
    onState('loading');
    new STLLoader().load(
      url,
      (loaded) => {
        if (cancelled) {
          loaded.dispose();
          return;
        }
        loaded.computeVertexNormals();
        loaded.computeBoundingBox();
        const size = loaded.boundingBox?.getSize(new Vector3()) ?? new Vector3(1, 1, 1);
        const longest = Math.max(size.x, size.y, size.z, 0.001);
        loaded.center();
        loaded.computeBoundingSphere();
        setScale(3.8 / longest);
        setMesh(loaded);
        onState('ready');
      },
      undefined,
      (error) => {
        if (cancelled) return;
        onState('failed', error instanceof Error ? error.message : 'STL could not be loaded');
      },
    );
    return () => {
      cancelled = true;
    };
  }, [onState, url]);

  useEffect(() => () => mesh?.dispose(), [mesh]);

  if (!mesh) return null;
  return (
    <mesh geometry={mesh} scale={scale} castShadow receiveShadow>
      <meshPhysicalMaterial color="#70f0b6" roughness={0.34} metalness={0.08} clearcoat={0.25} />
    </mesh>
  );
}

export interface GeometryViewerProps {
  geometry?: GeometryRef | null;
  designLabel?: string;
  projectName?: string;
  className?: string;
  compact?: boolean;
  onError?: (error: string) => void;
}

export function GeometryViewer({
  geometry,
  designLabel,
  projectName,
  className = '',
  compact = false,
  onError,
}: GeometryViewerProps) {
  const initial = useMemo(() => geometryViewerState(geometry), [geometry]);
  const [state, setState] = useState<ViewerState>(initial);
  const [error, setError] = useState<string | null>(null);
  const stlUrl = geometry?.status === 'ready' ? geometry.stl_url : null;

  useEffect(() => {
    setState(geometryViewerState(geometry));
    setError(geometry?.status === 'failed' || geometry?.status === 'skipped' ? geometry.error ?? 'Geometry is unavailable' : null);
  }, [geometry]);

  const updateState = useCallback((next: ViewerState, message?: string) => {
    setState(next);
    setError(message ?? null);
    if (message) onError?.(message);
  }, [onError]);

  return (
    <section className={`relative overflow-hidden rounded-2xl border border-line bg-panel ${className}`} aria-label="Project geometry viewer">
      <div className="absolute inset-x-0 top-0 z-10 flex items-start justify-between gap-3 p-4">
        <div>
          <div className="eyebrow">STL geometry</div>
          <strong className="block max-w-72 truncate text-sm text-white">{projectName ?? 'Selected project'}</strong>
        </div>
        <span className={`status-pill ${state === 'ready' ? 'status-live' : state === 'failed' ? 'status-fallback' : 'status-ready'}`}>
          <i />{state === 'ready' ? 'verified STL' : state}
        </span>
      </div>

      {stlUrl ? (
        <Canvas
          camera={{ position: [4.5, 3.2, 5.5], fov: 34, near: 0.01, far: 100 }}
          dpr={[1, 1.5]}
          shadows={!compact}
          className={compact ? 'min-h-48' : 'min-h-[26rem]'}
        >
          <color attach="background" args={['#08120f']} />
          <ambientLight intensity={1.35} />
          <directionalLight position={[4, 7, 5]} intensity={2.4} castShadow={!compact} />
          <directionalLight position={[-5, 2, -4]} intensity={0.8} color="#65c9ff" />
          <LoadedStl url={stlUrl} onState={updateState} />
          {!compact ? <ContactShadows position={[0, -2.1, 0]} opacity={0.32} scale={9} blur={2.5} /> : null}
          <OrbitControls makeDefault enableDamping autoRotate={!compact} autoRotateSpeed={0.45} />
        </Canvas>
      ) : (
        <div className={`flex items-center justify-center px-8 text-center ${compact ? 'min-h-48' : 'min-h-[26rem]'}`}>
          <div>
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full border border-line font-mono text-slate-500">3D</div>
            <strong className="text-sm text-slate-300">{state === 'pending' ? 'Geometry is being prepared' : 'No verified STL available'}</strong>
            <p className="mt-1 max-w-sm text-xs leading-relaxed text-slate-500">{error ?? 'Darwin shows only geometry returned as ready. A missing, skipped, or failed export is never presented as a successful result.'}</p>
          </div>
        </div>
      )}

      {designLabel ? <div className="absolute bottom-3 left-4 z-10 rounded-md border border-line bg-ink/80 px-2 py-1 font-mono text-[9px] text-slate-400">{designLabel}</div> : null}
    </section>
  );
}

export default GeometryViewer;

