import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

function Core({ dark, onSlow }: { dark: boolean; onSlow: () => void }) {
  const group = useRef<THREE.Group>(null);
  const particles = useRef<THREE.InstancedMesh>(null);
  const invalidate = useThree((state) => state.invalidate);
  const last = useRef(0);
  const frames = useRef(0);
  const slow = useRef(0);
  const pointer = useRef({ x: 0, y: 0 });
  const dust = useMemo(
    () =>
      Array.from({ length: 35 }, (_, i) => {
        const angle = i * 2.39996;
        return [
          Math.cos(angle) * (2 + (i % 4) * 0.2),
          Math.sin(angle) * (1.5 + (i % 3) * 0.15),
          -0.8 + (i % 5) * 0.2,
        ] as [number, number, number];
      }),
    [],
  );
  useLayoutEffect(() => {
    const matrix = new THREE.Object3D();
    dust.forEach((position, i) => {
      matrix.position.set(...position);
      matrix.scale.setScalar(i % 4 === 0 ? 1.8 : 1);
      matrix.updateMatrix();
      particles.current?.setMatrixAt(i, matrix.matrix);
    });
    if (particles.current) particles.current.instanceMatrix.needsUpdate = true;
    invalidate();
  }, [dust, invalidate]);
  useFrame((state, delta) => {
    if (!group.current) return;
    if (
      state.pointer.x !== pointer.current.x ||
      state.pointer.y !== pointer.current.y
    ) {
      last.current = state.clock.elapsedTime;
      pointer.current = { x: state.pointer.x, y: state.pointer.y };
    }
    const targetY = state.pointer.x * 0.2 + 0.3;
    const targetX = -state.pointer.y * 0.15 + 0.12;
    group.current.rotation.y = THREE.MathUtils.damp(
      group.current.rotation.y,
      targetY,
      5,
      delta,
    );
    group.current.rotation.x = THREE.MathUtils.damp(
      group.current.rotation.x,
      targetX,
      5,
      delta,
    );
    if (state.clock.elapsedTime - last.current < 2 && !document.hidden)
      state.invalidate();
    if (delta > 0.04 && frames.current > 3) slow.current++;
    frames.current++;
    if (frames.current > 90 && slow.current > 45) onSlow();
  });
  return (
    <>
      <ambientLight intensity={dark ? 1.3 : 1.8} />
      <directionalLight position={[3, 4, 5]} intensity={3.5} color="#e0fff5" />
      <pointLight position={[-3, 1, 2]} intensity={14} color="#18c6a1" />
      <pointLight position={[3, -2, 1]} intensity={9} color="#8687fa" />
      <group
        ref={group}
        rotation={[0.12, 0.3, -0.15]}
        onPointerMove={() => invalidate()}
      >
        <mesh rotation={[0.6, -0.3, 0.2]}>
          <torusKnotGeometry args={[0.68, 0.19, 112, 16, 2, 3]} />
          <meshStandardMaterial
            color={dark ? "#3ee4bc" : "#23bba0"}
            metalness={0.55}
            roughness={0.23}
          />
        </mesh>
        <mesh>
          <icosahedronGeometry args={[0.45, 0]} />
          <meshStandardMaterial
            color={dark ? "#aaffdf" : "#065e57"}
            metalness={0.65}
            roughness={0.15}
          />
        </mesh>
        <mesh rotation={[1.1, 0.4, 0.2]}>
          <torusGeometry args={[1.38, 0.007, 5, 96]} />
          <meshBasicMaterial
            color={dark ? "#376a67" : "#a5cbc2"}
            transparent
            opacity={0.7}
          />
        </mesh>
        <mesh rotation={[0.3, -0.6, -0.3]}>
          <torusGeometry args={[1.95, 0.006, 5, 96]} />
          <meshBasicMaterial
            color={dark ? "#345254" : "#bed2ce"}
            transparent
            opacity={0.6}
          />
        </mesh>
        <mesh rotation={[1.3, -0.4, -0.4]}>
          <torusGeometry args={[2.4, 0.004, 4, 96]} />
          <meshBasicMaterial
            color={dark ? "#405068" : "#cad3e0"}
            transparent
            opacity={0.4}
          />
        </mesh>
        {[
          [1.25, 0.6, 0.1],
          [-1.2, -0.6, 0.2],
          [0.6, -1.1, 0.7],
        ].map((p, i) => (
          <mesh key={i} position={p as [number, number, number]}>
            <sphereGeometry args={[0.045, 12, 12]} />
            <meshBasicMaterial color={i === 2 ? "#9996ff" : "#51dab5"} />
          </mesh>
        ))}
        <instancedMesh
          ref={particles}
          args={[undefined, undefined, dust.length]}
        >
          <sphereGeometry args={[0.01, 5, 5]} />
          <meshBasicMaterial
            color={dark ? "#8ca3b2" : "#6a8992"}
            transparent
            opacity={0.35}
          />
        </instancedMesh>
      </group>
    </>
  );
}

export default function AgentScene({
  dark,
  onFallback,
}: {
  dark: boolean;
  onFallback: () => void;
}) {
  const [visible, setVisible] = useState(!document.hidden);
  useEffect(() => {
    const handler = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, []);
  return (
    <Canvas
      camera={{ position: [0, 0, 5.6], fov: 43 }}
      dpr={[1, 1.5]}
      frameloop={visible ? "demand" : "never"}
      gl={{ antialias: true, alpha: true, powerPreference: "low-power" }}
      onCreated={({ gl }) =>
        gl.domElement.addEventListener("webglcontextlost", onFallback, {
          once: true,
        })
      }
    >
      <Core dark={dark} onSlow={onFallback} />
    </Canvas>
  );
}
