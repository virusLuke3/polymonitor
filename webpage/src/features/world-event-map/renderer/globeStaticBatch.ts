import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

/** Reuse the locked globe.gl tessellation and native objects for picking.
 * Opaque outlines with the same GPU transform can share a draw. Transparent
 * caps/strokes retain their original interleaving: batching them changes
 * overlapping alert colours. All polygon transforms are static between digests.
 */
export class GlobeStaticBatch {
  private originals: Array<{ object: any; auto: boolean; worldAuto: boolean; visible: boolean }> = [];
  private group = new THREE.Group();
  private occlusion: Array<{ object: any; sphere: THREE.Sphere; visible: boolean }> = [];
  private camera = new THREE.Vector3(NaN, NaN, NaN);
  private hidden = 0;

  rebuild(scene: any) {
    this.clear();
    scene.updateMatrixWorld(true);
    const groups = new Map<string, any[]>();
    scene.traverse((object: any) => {
      if (object.__globeObjType !== 'polygon' && object.parent?.__globeObjType !== 'polygon') return;
      this.originals.push({ object, auto: object.matrixAutoUpdate, worldAuto: object.matrixWorldAutoUpdate, visible: object.visible });
      object.matrixAutoUpdate = object.matrixWorldAutoUpdate = false;
      if (!object.isLineSegments || !object.visible || object.material.transparent
        || !object.geometry?.attributes.position?.count) return;
      const material = object.material;
      const key = JSON.stringify([material.color.getHex(), material.opacity, material.depthWrite,
        material.depthTest, material.blending, object.matrixWorld.elements]);
      const members = groups.get(key) || [];
      members.push(object); groups.set(key, members);
    });
    const batched = new Set<any>();
    let objects = 0;
    for (const members of groups.values()) {
      if (members.length < 8) continue;
      // BufferGeometry.copy avoids custom geometry constructors requiring args.
      const copies = members.map(object => new THREE.BufferGeometry().copy(object.geometry));
      const geometry = mergeGeometries(copies, false);
      copies.forEach(copy => copy.dispose());
      if (!geometry) continue;
      const batch = new THREE.LineSegments(geometry, members[0]!.material.clone());
      // Preserve GPU transform rounding, as well as every native vertex.
      batch.matrix.copy(members[0]!.matrixWorld);
      batch.matrixAutoUpdate = false;
      batch.raycast = () => {}; // Native originals retain identity and picking.
      this.group.add(batch);
      members.forEach(object => { object.visible = false; batched.add(object); });
      objects += members.length;
    }
    for (const { object, visible } of this.originals) {
      if (!visible || batched.has(object) || !object.geometry) continue;
      object.geometry.computeBoundingSphere();
      const sphere = object.geometry.boundingSphere?.clone().applyMatrix4(object.matrixWorld);
      if (sphere && Number.isFinite(sphere.radius)) this.occlusion.push({ object, sphere, visible });
    }
    scene.add(this.group);
    return { objects, batches: this.group.children.length };
  }
  /** Conservative sphere-vs-opaque-Earth occlusion. Never cull a limb-crossing
   * bound, a near-side region or any part merely outside the camera frustum. */
  cull(camera: THREE.Vector3, earthRadius = 100) {
    if (this.camera.equals(camera)) return this.hidden;
    this.camera.copy(camera); this.hidden = 0;
    const distance = camera.length();
    const earthAngle = distance > earthRadius ? Math.asin(earthRadius / distance) : 0;
    const tangentDistance = Math.sqrt(Math.max(0, distance * distance - earthRadius * earthRadius));
    const towardEarth = camera.clone().negate().normalize();
    const offset = new THREE.Vector3();
    for (const { object, sphere, visible } of this.occlusion) {
      offset.copy(sphere.center).sub(camera);
      const range = offset.length();
      const halfAngle = Math.asin(Math.min(1, sphere.radius / range));
      const angle = Math.acos(Math.max(-1, Math.min(1, offset.dot(towardEarth) / range)));
      const hidden = distance > earthRadius && range > sphere.radius
        && range - sphere.radius > tangentDistance
        && angle + halfAngle < earthAngle - 1e-6;
      object.visible = visible && !hidden;
      if (hidden) this.hidden++;
    }
    return this.hidden;
  }
  clear() {
    for (const { object, auto, worldAuto, visible } of this.originals) {
      object.visible = visible;
      object.matrixAutoUpdate = auto;
      object.matrixWorldAutoUpdate = worldAuto;
    }
    this.originals = []; this.occlusion = []; this.hidden = 0;
    this.camera.set(NaN, NaN, NaN);
    for (const batch of this.group.children) { batch.geometry.dispose(); batch.material.dispose(); }
    this.group.clear(); this.group.removeFromParent();
  }
}
