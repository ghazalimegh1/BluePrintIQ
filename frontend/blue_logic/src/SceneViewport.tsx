import { useEffect, useMemo, useRef } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { SceneElement, SceneResponse } from "./types";

interface Bounds {
  center: [number, number, number];
  radius: number;
  floor: number;
}

interface Props {
  scene: SceneResponse;
  selectedId: string | null;
  onSelect: (element: SceneElement | null) => void;
}

function getColor(element: SceneElement): string {
  const color = element.provenance.display_color;
  return typeof color === "string" ? color : "#83aaa6";
}

function useSceneBounds(elements: SceneElement[]): Bounds {
  return useMemo(() => {
    let minX = Infinity;
    let minY = Infinity;
    let minZ = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    let maxZ = -Infinity;
    for (const element of elements) {
      for (let index = 0; index < element.vertices.length; index += 3) {
        const x = element.vertices[index];
        const y = element.vertices[index + 2];
        const z = -element.vertices[index + 1];
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        minZ = Math.min(minZ, z);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
        maxZ = Math.max(maxZ, z);
      }
    }
    if (!Number.isFinite(minX)) {
      return { center: [0, 0, 0], radius: 25, floor: 0 };
    }
    const center: [number, number, number] = [
      (minX + maxX) / 2,
      (minY + maxY) / 2,
      (minZ + maxZ) / 2,
    ];
    const radius = Math.max(
      2,
      Math.hypot(maxX - minX, maxY - minY, maxZ - minZ) / 2,
    );
    return { center, radius, floor: minY };
  }, [elements]);
}

function SceneMesh({
  element,
  active,
  onSelect,
}: {
  element: SceneElement;
  active: boolean;
  onSelect: () => void;
}) {
  const geometry = useMemo(() => {
    const positions = new Float32Array(element.vertices.length);
    for (let index = 0; index < element.vertices.length; index += 3) {
      positions[index] = element.vertices[index];
      positions[index + 1] = element.vertices[index + 2];
      positions[index + 2] = -element.vertices[index + 1];
    }
    const result = new THREE.BufferGeometry();
    result.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    result.setIndex(element.indices);
    result.computeVertexNormals();
    result.computeBoundingSphere();
    return result;
  }, [element]);
  useEffect(() => () => geometry.dispose(), [geometry]);

  return (
    <mesh
      geometry={geometry}
      onClick={(event) => {
        event.stopPropagation();
        onSelect();
      }}
      castShadow
      receiveShadow
    >
      <meshStandardMaterial
        color={getColor(element)}
        emissive={active ? "#d28c48" : "#000000"}
        emissiveIntensity={active ? 0.6 : 0}
        roughness={0.78}
        metalness={0.08}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

function FocusSelectedElement({
  elements,
  selectedId,
  contextRadius,
  contextCenter,
}: {
  elements: SceneElement[];
  selectedId: string | null;
  contextRadius: number;
  contextCenter: [number, number, number];
}) {
  const { camera } = useThree();
  const controlsRef = useRef<any>(null);
  const animationRef = useRef<number | null>(null);

  useEffect(() => {
    if (!selectedId || !controlsRef.current) return;
    const element = elements.find(
      (item) => item.id === selectedId || item.global_id === selectedId,
    );
    if (!element || element.vertices.length < 3) return;

    let minX = Infinity;
    let minY = Infinity;
    let minZ = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    let maxZ = -Infinity;
    for (let index = 0; index < element.vertices.length; index += 3) {
      const x = element.vertices[index];
      const y = element.vertices[index + 2];
      const z = -element.vertices[index + 1];
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      minZ = Math.min(minZ, z);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
      maxZ = Math.max(maxZ, z);
    }
    const target = new THREE.Vector3(
      (minX + maxX) / 2,
      (minY + maxY) / 2,
      (minZ + maxZ) / 2,
    );
    const radius = Math.max(0.4, Math.hypot(maxX - minX, maxY - minY, maxZ - minZ) / 2);
    const direction = new THREE.Vector3(1, 0.8, 1).normalize();
    const startPosition = camera.position.clone();
    const startTarget = controlsRef.current.target.clone();
    const overviewTarget = new THREE.Vector3(...contextCenter);
    const overviewDistance = Math.max(contextRadius * 2.7, 8);
    const overviewPosition = overviewTarget.clone().addScaledVector(direction, overviewDistance);
    // Keep the selected element readable, but preserve enough surrounding
    // building context to make the evidence meaningful. A door-sized mesh
    // should never cause the camera to land inside the wall or lose the model.
    const contextualDistance = Math.max(radius * 8, Math.min(contextRadius * 0.24, 28));
    const endPosition = target.clone().addScaledVector(direction, contextualDistance);
    const endTarget = target.clone();
    const startedAt = performance.now();
    const duration = 1800;
    const animate = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / duration);
      // Two readable stages: pull back to the whole-building overview, then
      // travel toward the requested evidence. This lets the viewer understand
      // where the selected object sits before the closer inspection.
      const stage = progress < 0.42 ? 0 : 1;
      const stageProgress = stage === 0
        ? progress / 0.42
        : (progress - 0.42) / 0.58;
      const eased = stageProgress * stageProgress * (3 - 2 * stageProgress);
      if (stage === 0) {
        camera.position.lerpVectors(startPosition, overviewPosition, eased);
        controlsRef.current.target.lerpVectors(startTarget, overviewTarget, eased);
      } else {
        camera.position.lerpVectors(overviewPosition, endPosition, eased);
        controlsRef.current.target.lerpVectors(overviewTarget, endTarget, eased);
      }
      controlsRef.current.update();
      if (progress < 1) animationRef.current = requestAnimationFrame(animate);
      else animationRef.current = null;
    };
    if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
    animationRef.current = requestAnimationFrame(animate);
    return () => {
      if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
    };
  }, [camera, contextCenter, contextRadius, elements, selectedId]);

  return <OrbitControls ref={controlsRef} makeDefault enableDamping dampingFactor={0.08} />;
}

export function SceneViewport({ scene, selectedId, onSelect }: Props) {
  const bounds = useSceneBounds(scene.elements);
  const [centerX, centerY, centerZ] = bounds.center;
  const gridSize = Math.max(20, Math.min(800, bounds.radius * 3));
  const divisions = Math.max(10, Math.min(80, Math.ceil(gridSize / 2)));

  return (
    <Canvas
      camera={{ position: [centerX + bounds.radius * 1.7, centerY + bounds.radius * 1.3, centerZ + bounds.radius * 1.7], fov: 42, near: 0.05, far: bounds.radius * 100 }}
      dpr={[1, 1.5]}
      shadows
      gl={{ antialias: true, powerPreference: "high-performance" }}
      onPointerMissed={() => onSelect(null)}
    >
      <color attach="background" args={["#111918"]} />
      <ambientLight intensity={1.5} />
      <directionalLight position={[bounds.radius, bounds.radius * 2, bounds.radius]} intensity={2.2} castShadow />
      <directionalLight position={[-bounds.radius, bounds.radius, -bounds.radius]} intensity={0.75} />
      <gridHelper
        args={[gridSize, divisions, "#37514d", "#263936"]}
        position={[centerX, bounds.floor - Math.max(0.01, bounds.radius * 0.002), centerZ]}
      />
      {scene.elements.map((element) => (
        <SceneMesh
          key={element.id}
          element={element}
          active={element.id === selectedId || element.global_id === selectedId}
          onSelect={() => onSelect(element)}
        />
      ))}
      <FocusSelectedElement
        elements={scene.elements}
        selectedId={selectedId}
        contextRadius={bounds.radius}
        contextCenter={bounds.center}
      />
    </Canvas>
  );
}
