import { ContactShadows, OrbitControls } from '@react-three/drei';
import { Canvas, useFrame } from '@react-three/fiber';
import type { GeometryRef } from '@shared/contracts';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  BufferAttribute,
  BufferGeometry,
  Color,
  DoubleSide,
  MeshPhysicalMaterial,
} from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';

import {
  analyzeFinGeometry,
  buildFinPreviewGeometry,
  normalizeFinParams,
  type FinParamInput,
} from '../geometry/finPreview';

const MORPH_MS = 600;
const STL_FADE_MS = 400;
const BODY_DIAMETER_MM = 76.2;
const PREVIEW_OPACITY = 0.88;
const STL_OPACITY = 0.94;

type StlState = 'idle' | 'loading' | 'loaded' | 'failed';

export interface FinHeroProps {
  /** The current run champion. Used unless selectedParams is supplied. */
  championParams?: FinParamInput | null;
  /** An inspected design; takes precedence over the champion while selected. */
  selectedParams?: FinParamInput | null;
  /** Optional generation-zero design rendered as a wireframe comparison. */
  seedParams?: FinParamInput | null;
  /** Geometry for whichever design selectedParams/championParams describes. */
  geometry?: GeometryRef | null;
  generation?: number | null;
  designLabel?: string;
  className?: string;
  autoRotate?: boolean;
  showSeedGhost?: boolean;
  defaultShowSeedGhost?: boolean;
  onSeedGhostChange?: (visible: boolean) => void;
  onStlError?: (error: unknown) => void;
}

function easeInOutCubic(value: number): number {
  return value < 0.5 ? 4 * value ** 3 : 1 - ((-2 * value + 2) ** 3) / 2;
}

function asFloat32(attribute: BufferAttribute): Float32Array {
  return Float32Array.from(attribute.array as ArrayLike<number>);
}

function FinModel({
  target,
  seed,
  showSeed,
  geometryRef,
  onStlState,
  onStlError,
}: {
  target: FinParamInput;
  seed?: FinParamInput | null;
  showSeed: boolean;
  geometryRef?: GeometryRef | null;
  onStlState: (state: StlState) => void;
  onStlError?: (error: unknown) => void;
}) {
  const normalized = normalizeFinParams(target);
  const analysis = analyzeFinGeometry(normalized);
  const initialGeometry = useMemo(() => buildFinPreviewGeometry(normalized), []);
  const previewGeometryRef = useRef(initialGeometry);
  const previewMaterialRef = useRef<MeshPhysicalMaterial>(null);
  const stlMaterialRef = useRef<MeshPhysicalMaterial>(null);
  const morphFromRef = useRef(
    asFloat32(initialGeometry.getAttribute('position') as BufferAttribute),
  );
  const morphToRef = useRef(morphFromRef.current.slice());
  const morphStartedAtRef = useRef(0);
  const fadeStartedAtRef = useRef<number | null>(null);
  const [stlGeometry, setStlGeometry] = useState<BufferGeometry | null>(null);
  const onStlErrorRef = useRef(onStlError);
  onStlErrorRef.current = onStlError;

  const targetKey = `${normalized.root_chord}:${normalized.taper_ratio}:${normalized.semi_span}:${normalized.sweep_deg}:${normalized.thickness}:${normalized.edge_profile}`;
  const stlUrl =
    geometryRef?.status === 'ready' && geometryRef.stl_url ? geometryRef.stl_url : null;

  const seedGeometry = useMemo(
    () => (seed ? buildFinPreviewGeometry(seed) : null),
    [
      seed?.root_chord,
      seed?.taper_ratio,
      seed?.semi_span,
      seed?.sweep_deg,
      seed?.thickness,
      seed?.edge_profile,
    ],
  );

  useEffect(() => {
    const next = buildFinPreviewGeometry(normalized);
    const position = previewGeometryRef.current.getAttribute('position') as BufferAttribute;
    morphFromRef.current = asFloat32(position);
    morphToRef.current = asFloat32(next.getAttribute('position') as BufferAttribute);
    morphStartedAtRef.current = performance.now();
    next.dispose();
  }, [targetKey]);

  useEffect(
    () => () => {
      previewGeometryRef.current.dispose();
    },
    [],
  );

  useEffect(
    () => () => {
      seedGeometry?.dispose();
    },
    [seedGeometry],
  );

  useEffect(() => {
    let cancelled = false;
    setStlGeometry(null);
    fadeStartedAtRef.current = null;
    if (previewMaterialRef.current) previewMaterialRef.current.opacity = PREVIEW_OPACITY;

    if (!stlUrl) {
      onStlState('idle');
      return () => {
        cancelled = true;
      };
    }

    onStlState('loading');
    new STLLoader().load(
      stlUrl,
      (loaded) => {
        if (cancelled) {
          loaded.dispose();
          return;
        }
        loaded.computeVertexNormals();
        loaded.computeBoundingBox();
        loaded.computeBoundingSphere();
        setStlGeometry(loaded);
        fadeStartedAtRef.current = performance.now();
        onStlState('loaded');
      },
      undefined,
      (error) => {
        if (cancelled) return;
        onStlState('failed');
        onStlErrorRef.current?.(error);
      },
    );

    return () => {
      cancelled = true;
    };
  }, [stlUrl, onStlState]);

  useEffect(
    () => () => {
      stlGeometry?.dispose();
    },
    [stlGeometry],
  );

  useFrame(() => {
    const now = performance.now();
    const morphProgress = Math.min(1, (now - morphStartedAtRef.current) / MORPH_MS);
    if (morphProgress < 1) {
      const eased = easeInOutCubic(morphProgress);
      const position = previewGeometryRef.current.getAttribute('position') as BufferAttribute;
      const array = position.array as Float32Array;
      const from = morphFromRef.current;
      const to = morphToRef.current;
      for (let i = 0; i < array.length; i += 1) array[i] = from[i] + (to[i] - from[i]) * eased;
      position.needsUpdate = true;
      previewGeometryRef.current.computeVertexNormals();
      previewGeometryRef.current.computeBoundingBox();
      previewGeometryRef.current.computeBoundingSphere();
    }

    if (stlGeometry && fadeStartedAtRef.current !== null) {
      const progress = Math.min(1, (now - fadeStartedAtRef.current) / STL_FADE_MS);
      const eased = easeInOutCubic(progress);
      if (previewMaterialRef.current) {
        previewMaterialRef.current.opacity = PREVIEW_OPACITY * (1 - eased);
      }
      if (stlMaterialRef.current) stlMaterialRef.current.opacity = STL_OPACITY * eased;
      if (progress === 1) fadeStartedAtRef.current = null;
    }
  });

  const minX = analysis.bbox_mm[0];
  const maxX = analysis.bbox_mm[3];
  const modelWidth = maxX - minX;
  const bodyLength = Math.max(140, modelWidth + 48);
  const xCenter = (minX + maxX) / 2;
  const yCenter = (analysis.s - BODY_DIAMETER_MM) / 2;

  return (
    <group position={[-xCenter, -yCenter, 0]}>
      <mesh
        position={[xCenter, -BODY_DIAMETER_MM / 2, 0]}
        rotation={[0, 0, Math.PI / 2]}
        receiveShadow
      >
        <cylinderGeometry args={[BODY_DIAMETER_MM / 2, BODY_DIAMETER_MM / 2, bodyLength, 64, 1, true]} />
        <meshPhysicalMaterial
          color="#b8c7d9"
          transparent
          opacity={0.16}
          roughness={0.28}
          metalness={0.08}
          transmission={0.18}
          side={DoubleSide}
          depthWrite={false}
        />
      </mesh>

      <group rotation={[-Math.PI / 2, 0, 0]}>
        <mesh geometry={previewGeometryRef.current} castShadow receiveShadow>
          <meshPhysicalMaterial
            ref={previewMaterialRef}
            color="#25d9c7"
            emissive={new Color('#063d3b')}
            emissiveIntensity={0.4}
            metalness={0.2}
            roughness={0.26}
            clearcoat={0.72}
            clearcoatRoughness={0.2}
            transparent
            opacity={PREVIEW_OPACITY}
            side={DoubleSide}
            depthWrite={false}
          />
        </mesh>

        {stlGeometry ? (
          <mesh geometry={stlGeometry} castShadow receiveShadow>
            <meshPhysicalMaterial
              ref={stlMaterialRef}
              color="#8ef4e9"
              emissive={new Color('#0b4541')}
              emissiveIntensity={0.24}
              metalness={0.3}
              roughness={0.2}
              clearcoat={0.85}
              transparent
              opacity={0}
              side={DoubleSide}
              depthWrite={false}
            />
          </mesh>
        ) : null}

        {showSeed && seedGeometry ? (
          <mesh geometry={seedGeometry} renderOrder={4}>
            <meshBasicMaterial
              color="#91a4ba"
              transparent
              opacity={0.34}
              wireframe
              depthTest={false}
            />
          </mesh>
        ) : null}
      </group>
    </group>
  );
}

function Studio({
  target,
  seed,
  showSeed,
  geometry,
  autoRotate,
  onStlState,
  onStlError,
}: {
  target: FinParamInput;
  seed?: FinParamInput | null;
  showSeed: boolean;
  geometry?: GeometryRef | null;
  autoRotate: boolean;
  onStlState: (state: StlState) => void;
  onStlError?: (error: unknown) => void;
}) {
  const analysis = analyzeFinGeometry(target);
  const groundY = -(analysis.s + BODY_DIAMETER_MM) / 2 - 5;

  return (
    <>
      <color attach="background" args={['#071016']} />
      <ambientLight intensity={0.58} />
      <hemisphereLight args={['#d9fbff', '#10151b', 1.15]} />
      <directionalLight
        position={[135, 190, 125]}
        intensity={3.2}
        color="#e8ffff"
        castShadow
        shadow-mapSize={[512, 512]}
      />
      <directionalLight position={[-125, 65, -90]} intensity={1.8} color="#5379ff" />
      <pointLight position={[35, -15, 150]} intensity={900} distance={500} color="#1fe3c8" />

      <FinModel
        target={target}
        seed={seed}
        showSeed={showSeed}
        geometryRef={geometry}
        onStlState={onStlState}
        onStlError={onStlError}
      />

      <ContactShadows
        position={[0, groundY, 0]}
        opacity={0.42}
        scale={300}
        blur={2.6}
        far={170}
        resolution={256}
        frames={1}
        color="#020607"
      />
      <OrbitControls
        makeDefault
        enableDamping
        dampingFactor={0.06}
        autoRotate={autoRotate}
        autoRotateSpeed={0.42}
        minDistance={150}
        maxDistance={760}
        target={[0, 0, 0]}
      />
    </>
  );
}

function badgeFor(
  state: StlState,
  geometry: GeometryRef | null | undefined,
): { label: string; tone: string } {
  if (state === 'loading') return { label: 'Verifying geometry…', tone: '#e6b45e' };
  if (state === 'failed') return { label: 'Analytic preview', tone: '#e6b45e' };
  if (state === 'loaded') {
    const onshapeVerified =
      geometry?.source === 'onshape_config' ||
      geometry?.source === 'onshape_feature' ||
      geometry?.source === 'cache';
    return onshapeVerified
      ? { label: 'Onshape-verified ✓', tone: '#44e4c1' }
      : { label: 'CAD preview loaded', tone: '#7fc9ff' };
  }
  return { label: 'Live analytic preview', tone: '#8fa2b7' };
}

export function FinHero({
  championParams,
  selectedParams,
  seedParams,
  geometry,
  generation,
  designLabel,
  className,
  autoRotate = true,
  showSeedGhost,
  defaultShowSeedGhost = false,
  onSeedGhostChange,
  onStlError,
}: FinHeroProps) {
  const target = selectedParams ?? championParams ?? normalizeFinParams(null);
  const [internalShowSeed, setInternalShowSeed] = useState(defaultShowSeedGhost);
  const [stlState, setStlState] = useState<StlState>('idle');
  const showSeed = showSeedGhost ?? internalShowSeed;
  const badge = badgeFor(stlState, geometry);
  const calls = geometry?.onshape_calls ?? 0;

  const updateGhost = () => {
    const next = !showSeed;
    if (showSeedGhost === undefined) setInternalShowSeed(next);
    onSeedGhostChange?.(next);
  };

  // Stable callback avoids restarting an in-flight STL request every render.
  const handleStlState = useRef<(state: StlState) => void>(() => undefined);
  handleStlState.current = setStlState;
  const stableSetStlState = useMemo(() => (state: StlState) => handleStlState.current(state), []);

  return (
    <section
      className={className}
      aria-label="3D fin champion"
      style={{
        position: 'relative',
        minHeight: 320,
        overflow: 'hidden',
        border: '1px solid rgba(116, 150, 170, 0.2)',
        borderRadius: 18,
        background: '#071016',
      }}
    >
      <Canvas
        dpr={[1, 1.5]}
        camera={{ fov: 34, near: 0.1, far: 2000, position: [270, 205, 330] }}
        gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
        shadows
      >
        <Studio
          target={target}
          seed={seedParams}
          showSeed={showSeed}
          geometry={geometry}
          autoRotate={autoRotate}
          onStlState={stableSetStlState}
          onStlError={onStlError}
        />
      </Canvas>

      <div
        data-geometry-state={stlState}
        style={{
          position: 'absolute',
          top: 14,
          left: 14,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '7px 10px',
          border: `1px solid ${badge.tone}55`,
          borderRadius: 999,
          background: 'rgba(4, 11, 16, 0.78)',
          color: badge.tone,
          font: '600 11px/1.2 "JetBrains Mono", ui-monospace, monospace',
          letterSpacing: '0.045em',
          textTransform: 'uppercase',
          backdropFilter: 'blur(10px)',
          pointerEvents: 'none',
        }}
      >
        <span
          aria-hidden="true"
          style={{ width: 6, height: 6, borderRadius: '50%', background: badge.tone }}
        />
        {badge.label}
        {calls > 0 ? ` · ${calls} call${calls === 1 ? '' : 's'}` : ''}
      </div>

      {designLabel || (generation !== null && generation !== undefined) ? (
        <div
          style={{
            position: 'absolute',
            left: 16,
            bottom: 15,
            color: '#e6f4f5',
            font: '600 12px/1.35 Inter, ui-sans-serif, sans-serif',
            textShadow: '0 1px 12px #000',
            pointerEvents: 'none',
          }}
        >
          {designLabel ?? 'Champion'}
          {generation !== null && generation !== undefined ? ` · generation ${generation}` : ''}
        </div>
      ) : null}

      {seedParams ? (
        <button
          type="button"
          aria-pressed={showSeed}
          onClick={updateGhost}
          style={{
            position: 'absolute',
            right: 14,
            top: 14,
            padding: '7px 10px',
            border: '1px solid rgba(145, 164, 186, 0.35)',
            borderRadius: 999,
            background: showSeed ? 'rgba(55, 79, 96, 0.86)' : 'rgba(4, 11, 16, 0.76)',
            color: showSeed ? '#eefaff' : '#a4b2c1',
            cursor: 'pointer',
            font: '600 11px/1.2 Inter, ui-sans-serif, sans-serif',
            backdropFilter: 'blur(10px)',
          }}
        >
          {showSeed ? 'Hide seed' : 'Compare seed'}
        </button>
      ) : null}
    </section>
  );
}

export default FinHero;
