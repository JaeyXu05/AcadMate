import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import type { CloudGraphProps, CloudNode } from '../types/cloud';

/**
 * 3D 云图组件（Three.js 银河系渲染）。
 *
 * - nodes / edges 由后端 `GET /api/cloud/graph` 提供；点位为预计算的银河盘坐标。
 * - 715 位导师用一块 `InstancedMesh` + 自定义 ShaderMaterial 渲染：每个实例是一个
 *   面向相机的 billboard，亮/色/大小/径向亮度都走顶点&片元属性，心跳脉冲在 GPU 完成，
 *   从"715 次 draw call + 逐帧改材质"降到"1 次 draw call"，显著降低卡顿。
 * - 消费 build_cloud.py 生成的 `lum`（学术亮度）与 `core_lum`（径向中心亮度），
 *   复刻银河"越近亮核越亮"的纵深。
 * - 银河背景：沿旋臂星尘 + 柔和星云 + 中央亮核（HANDOVER 规格），与 `SPIRAL` 同参。
 * - 交互：拖拽旋转 / 滚轮缩放 / 自动缓转；点击 → onSelectNode(id)；悬停 → onHoverNode(id)。
 */

// 银河盘常量（与 cloud3d/build_cloud.py 的布局一致，供背景装饰同参使用）
const SPIRAL = { r_in: 170, r_out: 540, turns: 1.4, arms: 6 };

/** 生成柔和发光贴图（径向渐变），供星云/亮核等装饰与 billboard 采样 */
function makeGlowTexture(inner: string, mid: string): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 128;
  const ctx = canvas.getContext('2d')!;
  const grd = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, inner);
  grd.addColorStop(0.25, mid);
  grd.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = grd;
  ctx.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(canvas);
}

/** 沿对数螺旋线生成一批装饰粒子坐标（星尘）。t ∈ [t0,t1] 径向均布，Y 薄盘。 */
function spiralDust(cfg: typeof SPIRAL, count: number, t0: number, t1: number) {
  const positions = new Float32Array(count * 3);
  const turn = cfg.turns * Math.PI * 2;
  for (let i = 0; i < count; i++) {
    // 随机挑臂
    const arm = Math.floor(Math.random() * cfg.arms);
    const phase = (arm * Math.PI * 2) / cfg.arms;
    if (Math.random() < 0.5) {
      // 径向随机（螺旋盘主体）
      const t = t0 + Math.random() * (t1 - t0);
      const rBase = cfg.r_in * Math.pow(cfg.r_out / cfg.r_in, t);
      const th = phase + t * turn + (Math.random() - 0.5) * 0.18;
      const u = (Math.random() - 0.5) * 16; // 臂两侧展开
      const drdt = rBase * Math.log(cfg.r_out / cfg.r_in);
      const tx = drdt * Math.cos(th) - rBase * turn * Math.sin(th);
      const tz = drdt * Math.sin(th) + rBase * turn * Math.cos(th);
      const tl = Math.hypot(tx, tz) || 1;
      const nx = -tz / tl;
      const nz = tx / tl;
      positions[i * 3] = rBase * Math.cos(th) + u * nx;
      positions[i * 3 + 2] = rBase * Math.sin(th) + u * nz;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 6;
    } else {
      // 背景散点（径向散布更广）
      const r = cfg.r_in + Math.random() * (cfg.r_out - cfg.r_in) * 1.6;
      const th = Math.random() * Math.PI * 2;
      positions[i * 3] = r * Math.cos(th);
      positions[i * 3 + 1] = (Math.random() - 0.5) * 40;
      positions[i * 3 + 2] = r * Math.sin(th);
    }
  }
  return positions;
}

export default function CloudGraph({
  nodes,
  edges,
  selectedId,
  onSelectNode,
  onHoverNode,
  loading,
  className,
  style,
}: CloudGraphProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const hoverRef = useRef<HTMLDivElement>(null);

  // 组件内部跨渲染闭包共享的 scene 状态
  const applySelectionRef = useRef<() => void>(() => {});
  const hoverInfoRef = useRef<{ x: number; y: number; node: CloudNode } | null>(null);
  const selectedNodesRef = useRef<Set<string>>(new Set());

  // 状态同步（数据 / 选中 / 悬停变化时触发）
  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;
  const edgesRef = useRef(edges);
  edgesRef.current = edges;
  const selRef = useRef<string | undefined>(selectedId ?? undefined);
  const hoveredRef = useRef<string | null>(null);
  const onHoverNodeRef = useRef(onHoverNode);
  onHoverNodeRef.current = onHoverNode;

  // ============ 初始化 Three.js 场景（依赖 nodes，数据到达后（重）建） ============
  useEffect(() => {
    const mount = mountRef.current;
    // 数据未到（nodes 为空）时不建场景，避免 InstancedMesh 以 0 实例一次性渲染；
    // 数据到达后本 effect 因 [nodes] 变化重跑，从零重建全部实例。
    if (!mount || !nodes || nodes.length === 0) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x03030a);

    const camera = new THREE.PerspectiveCamera(55, mount.clientWidth / mount.clientHeight, 0.1, 8000);
    camera.position.set(0, 950, 1400);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.5;
    controls.minDistance = 80;
    controls.maxDistance = 5000;

    // ---------- 银河背景（纯装饰，非导师，不可交互） ----------
    const bgDust = new THREE.Group();
    scene.add(bgDust);

    // 沿旋臂星尘：让旋臂有实体颗粒感
    const armGeo = new THREE.BufferGeometry();
    const armPos = spiralDust(SPIRAL, 2600, 0.12, 0.95);
    armGeo.setAttribute('position', new THREE.BufferAttribute(armPos, 3));
    const armDust = new THREE.Points(
      armGeo,
      new THREE.PointsMaterial({
        size: 1.6,
        color: 0x9db8ff,
        transparent: true,
        opacity: 0.5,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    );
    bgDust.add(armDust);

    // 远处深空星尘（缓慢自转的背景粒子）
    const deepGeo = new THREE.BufferGeometry();
    const deepCount = 1200;
    const deepPos = new Float32Array(deepCount * 3);
    for (let i = 0; i < deepCount; i++) {
      const r = 700 + Math.random() * 2600;
      const th = Math.random() * Math.PI * 2;
      const ph = Math.acos(2 * Math.random() - 1);
      deepPos[i * 3] = r * Math.sin(ph) * Math.cos(th);
      deepPos[i * 3 + 1] = r * Math.sin(ph) * Math.sin(th) * 0.6;
      deepPos[i * 3 + 2] = r * Math.cos(ph);
    }
    deepGeo.setAttribute('position', new THREE.BufferAttribute(deepPos, 3));
    const deepDust = new THREE.Points(
      deepGeo,
      new THREE.PointsMaterial({
        size: 1.2,
        color: 0x4466aa,
        transparent: true,
        opacity: 0.45,
        depthWrite: false,
      }),
    );
    bgDust.add(deepDust);

    // 沿臂柔和星云（加性发光）
    const nebulaTex = makeGlowTexture('rgba(255,255,255,0.9)', 'rgba(120,160,255,0.35)');
    const nebulaColors = ['#4455dd', '#2255aa', '#5533aa', '#224477'];
    for (let arm = 0; arm < SPIRAL.arms; arm++) {
      const phase = (arm * Math.PI * 2) / SPIRAL.arms;
      const pieces = 2 + (arm % 2);
      for (let p = 0; p < pieces; p++) {
        const t = 0.45 + Math.random() * 0.45;
        const r = SPIRAL.r_in * Math.pow(SPIRAL.r_out / SPIRAL.r_in, t);
        const th = phase + t * SPIRAL.turns * Math.PI * 2 + (Math.random() - 0.5) * 0.4;
        const mat = new THREE.SpriteMaterial({
          map: nebulaTex,
          color: nebulaColors[arm % nebulaColors.length],
          transparent: true,
          opacity: 0.16 + Math.random() * 0.12,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        });
        const sprite = new THREE.Sprite(mat);
        sprite.position.set(r * Math.cos(th), (Math.random() - 0.5) * 8, r * Math.sin(th));
        const s = 260 + Math.random() * 220;
        sprite.scale.set(s, s * 0.5, 1); // 长轴沿臂，压扁
        bgDust.add(sprite);
      }
    }

    // 中央亮核：同心暖金→白发光层 + 暗色黑洞环
    const coreTex = makeGlowTexture('rgba(255,240,210,1)', 'rgba(255,190,90,0.5)');
    const coreScales = [150, 95, 55, 26];
    const coreColors = ['#ffd98a', '#ffe9b8', '#fff4d8', '#ffffff'];
    coreScales.forEach((s, i) => {
      const mat = new THREE.SpriteMaterial({
        map: coreTex,
        color: coreColors[i],
        transparent: true,
        opacity: 0.5 - i * 0.07,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      const sp = new THREE.Sprite(mat);
      sp.position.set(0, 0, 0);
      sp.scale.setScalar(s);
      bgDust.add(sp);
    });
    // 暗色黑洞环衬托亮核
    const ringTex = makeGlowTexture('rgba(0,0,0,0)', 'rgba(0,0,0,0.85)');
    const ringRing = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: ringTex, transparent: true, opacity: 0.5, depthWrite: false }),
    );
    ringRing.position.set(0, 0, 0);
    ringRing.scale.setScalar(380);
    bgDust.add(ringRing);

    // ---------- 导师星点：单块 InstancedMesh（billboard + 着色器属性） ----------
    const COUNT = nodesRef.current.length;
    const instGeo = new THREE.BufferGeometry();
    // 单位平面，顶点/片元着色器负责 billboard + 发光
    const positions = new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, 1, 1, 0, -1, 1, 0, -1, -1, 0]);
    const uvs = new Float32Array([0, 0, 1, 0, 1, 1, 1, 1, 0, 1, 0, 0]);
    instGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    instGeo.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));

    const instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(COUNT * 3), 3);
    const instanceSize = new THREE.InstancedBufferAttribute(new Float32Array(COUNT), 1);
    const instanceLum = new THREE.InstancedBufferAttribute(new Float32Array(COUNT), 1);
    const instanceOffset = new THREE.InstancedBufferAttribute(new Float32Array(COUNT * 3), 3);

    instGeo.setAttribute('aColor', instanceColor);
    instGeo.setAttribute('aSize', instanceSize);
    instGeo.setAttribute('aLum', instanceLum);
    instGeo.setAttribute('aCenter', instanceOffset);

    // quad（6 顶点）作为公告板精灵：顶点着色器用视图矩阵的 right/up 把单位四边形
    // 偏移成面向相机的屏幕空间四边形；片元用 uv 计算径向发光（不能用 gl_PointCoord，
    // 那只对 GL_POINTS 有效，这里是非点原语的 InstancedMesh）。
    const vertexShader = /* glsl */ `
      attribute vec3 aColor;
      attribute float aSize;
      attribute float aLum;
      attribute vec3 aCenter;
      attribute vec2 uv;
      varying vec3 vColor;
      varying float vLum;
      varying float vPulse;
      varying vec2 vUv;
      uniform float uTime;
      uniform float uPixelRatio;
      uniform float uSize;
      void main() {
        vColor = aColor;
        vLum = aLum;
        vUv = uv;
        // 呼吸脉冲（差异由 instance id 相位引入），片元亮度乘它，GPU 完成不逐帧改材质
        vPulse = 0.82 + 0.18 * sin(uTime * 1.4 + float(gl_InstanceID) * 0.53);
        // 中心点变换到相机空间
        vec4 centerView = modelViewMatrix * vec4(aCenter, 1.0);
        // 取视图矩阵的 right / up（世界→视图矩阵的列），即公告板朝向相机的基础向量
        vec3 right = vec3(viewMatrix[0][0], viewMatrix[1][0], viewMatrix[2][0]);
        vec3 up    = vec3(viewMatrix[0][1], viewMatrix[1][1], viewMatrix[2][1]);
        float halfSize = 0.5 * aSize * uSize * uPixelRatio;
        vec3 corner = centerView.xyz
                    + (uv.x - 0.5) * halfSize * right
                    + (uv.y - 0.5) * halfSize * up;
        gl_Position = projectionMatrix * vec4(corner, 1.0);
      }
    `;

    const fragmentShader = /* glsl */ `
      varying vec3 vColor;
      varying float vLum;
      varying float vPulse;
      varying vec2 vUv;
      uniform float uCoreLum; // 全局径向亮度进度（0..1，整体抬升中心）
      uniform float uDimmer;  // 非选中时的整体压暗（0..1，1=正常）
      void main() {
        // 用 uv 算径向距离（0..1 居中 → 边缘距离 0.5→1），做中心亮边缘透明的发光圆盘
        float d = length(vUv - vec2(0.5)) * 2.0; // 0=中心 … 1=边缘
        float glow = smoothstep(1.0, 0.12, d);
        float core = smoothstep(0.56, 0.0, d);
        float alpha = (glow * 0.85 + core * 0.55) * vLum * vPulse * uDimmer;
        vec3 col = vColor * (0.6 + 0.8 * core) + vec3(0.25) * core;
        gl_FragColor = vec4(col, alpha);
      }
    `;

    const instMat = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uPixelRatio: { value: Math.min(window.devicePixelRatio, 2) },
        uSize: { value: 2.4 },
        uCoreLum: { value: 0 },
        uDimmer: { value: 1 },
      },
      vertexShader,
      fragmentShader,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    const stars = new THREE.InstancedMesh(instGeo, instMat, COUNT);
    stars.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    stars.frustumCulled = true;
    scene.add(stars);

    // 节点实例数据写入（位置 / 颜色 / 大小 / 亮度，尺寸由 build_cloud 的 size*lum 决定）
    function writeInstances() {
      const nodesArr = nodesRef.current;
      const starByNode: Record<string, { node: CloudNode; color: THREE.Color }> = {};
      const color = new THREE.Color();
      for (let i = 0; i < nodesArr.length; i++) {
        const n = nodesArr[i];
        const p = new THREE.Vector3(n.x ?? 0, n.y ?? 0, n.z ?? 0);
        stars.setMatrixAt(i, new THREE.Matrix4().setPosition(p));
        color.set(n.color ?? '#667eea');
        instanceColor.setXYZ(i, color.r, color.g, color.b);
        const s = (n.size ?? 1.2) * (0.9 + 0.6 * (n.lum ?? 0.8));
        instanceSize.setX(i, Math.max(10, s * 7));
        instanceLum.setX(i, n.lum ?? 0.8);
        starByNode[n.id] = { node: n, color: color.clone() };
      }
      instanceColor.needsUpdate = true;
      instanceSize.needsUpdate = true;
      instanceLum.needsUpdate = true;
      stars.instanceMatrix.needsUpdate = true;
      starByNodeRef.current = starByNode;
    }
    const starByNodeRef = { current: {} as Record<string, { node: CloudNode; color: THREE.Color }> };
    writeInstances();

    // ---------- 选中/邻居高亮（改色 + 改透明度） ----------
    applySelectionRef.current = () => {
      const sel = selRef.current;
      const neighborIds = new Set<string>();
      if (sel) {
        edgesRef.current.forEach((e) => {
          if (e.source === sel) neighborIds.add(e.target);
          if (e.target === sel) neighborIds.add(e.source);
        });
      }
      const dimmer = sel ? 0.14 : 1.0;
      const isSel = (id: string) => id === sel;
      const isNeighbor = (id: string) => neighborIds.has(id);
      instMat.uniforms.uDimmer.value = dimmer;
      // 选中的星放大，并单独提亮：通过该实例属性覆盖
      const { current: starByNode } = starByNodeRef;
      const nodesArr = nodesRef.current;
      const white = new THREE.Color(0xffffff);
      for (let i = 0; i < nodesArr.length; i++) {
        const n = nodesArr[i];
        const entry = starByNode[n.id];
        if (!entry) continue;
        const s = (n.size ?? 1.2) * (0.9 + 0.6 * (n.lum ?? 0.8));
        if (isSel(n.id)) {
          instanceSize.setX(i, Math.max(10, s * 7) * 1.55);
          instanceColor.setXYZ(i, white.r, white.g, white.b);
          instanceLum.setX(i, 1.0);
        } else if (!sel || isNeighbor(n.id)) {
          // 未选中态：保持原色；邻居态保持原样（相对 dimmer 提亮由 uDimmer 全局体现）
          instanceColor.setXYZ(i, entry.color.r, entry.color.g, entry.color.b);
          instanceSize.setX(i, Math.max(10, s * 7));
          instanceLum.setX(i, n.lum ?? 0.8);
        } else {
          // 其余压暗（uDimmer 已全局压暗，这里再叠一层）
          instanceColor.setXYZ(i, entry.color.r * 0.35, entry.color.g * 0.35, entry.color.b * 0.35);
          instanceLum.setX(i, (n.lum ?? 0.8) * 0.3);
        }
      }
      instanceColor.needsUpdate = true;
      instanceSize.needsUpdate = true;
      instanceLum.needsUpdate = true;
      selectedNodesRef.current = neighborIds;
    };
    applySelectionRef.current();

    // ---------- 交互：拾取导师星（屏幕投影距离近似，星点为 billboard，视觉尺寸小） ----------
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    const tmpMatrix = new THREE.Matrix4();
    function pickByDistance(clientX: number, clientY: number): number | null {
      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const nodesArr = nodesRef.current;
      const ray = raycaster.ray;
      let bestIdx: number | null = null;
      let bestD = Infinity;
      for (let i = 0; i < nodesArr.length; i++) {
        stars.getMatrixAt(i, tmpMatrix);
        const c = new THREE.Vector3().setFromMatrixPosition(tmpMatrix);
        const proj = new THREE.Vector3().subVectors(c, ray.origin);
        const t = proj.dot(ray.direction);
        const clampT = Math.max(0, t);
        const closest = new THREE.Vector3().copy(ray.origin).addScaledVector(ray.direction, clampT);
        const dist = closest.distanceTo(c);
        if (dist < bestD) {
          bestD = dist;
          bestIdx = i;
        }
      }
      // 阈值：星体视觉半径内才算命中
      if (bestIdx !== null && bestD < 26) return bestIdx;
      return null;
    }

    const onPointerMove = (e: PointerEvent) => {
      renderer.domElement.style.cursor = 'grab';
      const idx = pickByDistance(e.clientX, e.clientY);
      if (idx !== null) {
        renderer.domElement.style.cursor = 'pointer';
        const node = nodesRef.current[idx];
        if (node && hoveredRef.current !== node.id) {
          hoveredRef.current = node.id;
          hoverInfoRef.current = { x: e.clientX, y: e.clientY, node };
          updateHoverCard();
          onHoverNodeRef.current?.(node.id);
        }
      } else {
        if (hoveredRef.current !== null) {
          hoveredRef.current = null;
          hoverInfoRef.current = null;
          if (hoverRef.current) hoverRef.current.style.display = 'none';
          onHoverNodeRef.current?.(null);
        }
        renderer.domElement.style.cursor = 'grab';
      }
    };
    const onClick = (e: MouseEvent) => {
      if (e.detail > 1) return;
      const idx = pickByDistance(e.clientX, e.clientY);
      onSelectNode?.(idx !== null ? nodesRef.current[idx]?.id ?? null : null);
    };
    renderer.domElement.addEventListener('pointermove', onPointerMove);
    renderer.domElement.addEventListener('click', onClick);

    // ---------- 悬浮卡 ----------
    function updateHoverCard() {
      const el = hoverRef.current;
      if (!el) return;
      const info = hoverInfoRef.current;
      if (!info) {
        el.style.display = 'none';
        return;
      }
      const { x, y, node } = info;
      el.style.display = 'block';
      el.style.left = `${x + 14}px`;
      el.style.top = `${y + 8}px`;
      el.innerHTML = `
        <div class="cloud-hover-name">${escapeHtml(node.name)}</div>
        <div class="cloud-hover-dept">${escapeHtml(node.department ?? '')}</div>
        ${node.domain_name ? `<div class="cloud-hover-domain">${escapeHtml(node.domain_name)}</div>` : ''}
      `;
    }
    function escapeHtml(s: string): string {
      return s.replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string
      ));
    }

    // ---------- 动画 ----------
    let raf = 0;
    function animate() {
      raf = requestAnimationFrame(animate);
      controls.update();
      const t = performance.now() * 0.001;
      instMat.uniforms.uTime.value = t;
      bgDust.rotation.y = t * 0.004; // 背景与旋臂同步缓转
      renderer.render(scene, camera);
    }
    animate();

    // ---------- 尺寸自适应 ----------
    const onResize = () => {
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      if (!w || !h) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(mount);

    // 初始选中态
    applySelectionRef.current();

    // ---------- 清理 ----------
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      renderer.domElement.removeEventListener('pointermove', onPointerMove);
      renderer.domElement.removeEventListener('click', onClick);
      controls.dispose();
      instGeo.dispose();
      instMat.dispose();
      // CanvasTexture 本身有 dispose；不要 Object.values(tex) 遍历——那会对字符串等属性误调用
      nebulaTex.dispose();
      coreTex.dispose();
      ringTex.dispose();
      stars.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes]);

  // 选中变化
  useEffect(() => {
    selRef.current = selectedId ?? undefined;
    applySelectionRef.current();
  }, [selectedId]);

  return (
    <div
      className={className}
      style={{
        position: 'absolute',
        inset: 0,
        background: 'radial-gradient(ellipse at center, rgba(40,50,90,0.25) 0%, rgba(3,3,10,1) 72%)',
        cursor: 'grab',
        overflow: 'hidden',
        ...style,
      }}
      ref={mountRef}
    >
      {/* 悬浮卡（position fixed，跟随鼠标） */}
      <div
        ref={hoverRef}
        style={{
          display: 'none',
          position: 'fixed',
          zIndex: 30,
          pointerEvents: 'none',
          background: 'rgba(10,14,30,0.9)',
          border: '1px solid rgba(140,160,255,0.35)',
          borderRadius: 8,
          padding: '6px 10px',
          color: '#fff',
          fontSize: 12,
          boxShadow: '0 4px 18px rgba(0,0,0,0.5)',
          whiteSpace: 'nowrap',
        }}
      />
      {loading && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'rgba(255,255,255,0.6)',
            background: 'rgba(0,0,0,0.35)',
            pointerEvents: 'none',
            fontSize: 14,
            letterSpacing: 0.1,
          }}
        >
          正在加载星云图…
        </div>
      )}
      {!loading && nodes.length > 0 && (
        <div
          style={{
            position: 'absolute',
            left: 16,
            bottom: 16,
            fontSize: 12,
            color: 'rgba(255,255,255,0.4)',
            pointerEvents: 'none',
            letterSpacing: 0.04,
          }}
        >
          <b style={{ color: '#8ab0ff' }}>拖拽</b> 旋转 · <b style={{ color: '#8ab0ff' }}>滚轮</b> 缩放 ·{' '}
          <b style={{ color: '#8ab0ff' }}>点击</b> 导师星 查看详情
        </div>
      )}
    </div>
  );
}