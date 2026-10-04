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
      members.forEach(object => { object.visible = false; });
      objects += members.length;
    }
    scene.add(this.group);
    return { objects, batches: this.group.children.length };
  }
  clear() {
    for (const { object, auto, worldAuto, visible } of this.originals) {
      object.visible = visible;
      object.matrixAutoUpdate = auto;
      object.matrixWorldAutoUpdate = worldAuto;
    }
    this.originals = [];
    for (const batch of this.group.children) { batch.geometry.dispose(); batch.material.dispose(); }
    this.group.clear(); this.group.removeFromParent();
  }
}
