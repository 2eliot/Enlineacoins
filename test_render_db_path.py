#!/usr/bin/env python3
"""
Test script para verificar la configuración de base de datos compatible con Render
"""

import os
import sqlite3
import sys

def test_render_db_path():
    """Prueba la configuración de ruta de base de datos para Render"""
    print("🔍 Probando configuración de base de datos para Render...")
    
    # Simular entorno de Render
    os.environ['RENDER'] = '1'
    
    # Importar función después de configurar la variable de entorno
    sys.path.append('.')
    from app import get_render_compatible_db_path, DATABASE, get_db_connection_optimized, return_db_connection
    
    print(f"✅ Ruta de base de datos: {DATABASE}")
    print(f"✅ Directorio actual: {os.getcwd()}")
    print(f"✅ Variable RENDER: {os.environ.get('RENDER')}")
    
    # Verificar que la ruta es correcta para Render
    expected_path = 'usuarios.db'
    if DATABASE == expected_path:
        print(f"✅ Ruta correcta para Render: {DATABASE}")
    else:
        print(f"❌ Ruta incorrecta. Esperado: {expected_path}, Obtenido: {DATABASE}")
        return False
    
    # Probar conexión optimizada
    try:
        conn = get_db_connection_optimized()
        print("✅ Conexión optimizada establecida correctamente")
        
        # Probar una consulta simple
        cursor = conn.execute("SELECT 1 as test")
        result = cursor.fetchone()
        if result and result[0] == 1:
            print("✅ Consulta de prueba exitosa")
        else:
            print("❌ Error en consulta de prueba")
            return False
        
        return_db_connection(conn)
        print("✅ Conexión cerrada correctamente")
        
    except Exception as e:
        print(f"❌ Error en conexión optimizada: {e}")
        return False
    
    # Verificar que el archivo de base de datos se crea en el directorio correcto
    if os.path.exists(DATABASE):
        print(f"✅ Archivo de base de datos existe: {DATABASE}")
        
        # Verificar que está en el directorio raíz del proyecto
        if os.path.dirname(DATABASE) == '' or os.path.dirname(DATABASE) == '.':
            print("✅ Base de datos en directorio raíz (compatible con Render)")
        else:
            print(f"❌ Base de datos no está en directorio raíz: {os.path.dirname(DATABASE)}")
            return False
    else:
        print(f"⚠️  Archivo de base de datos no existe aún: {DATABASE}")
    
    return True

def test_profitability_functions():
    """Prueba las funciones de rentabilidad con la nueva configuración"""
    print("\n🔍 Probando funciones de rentabilidad...")
    
    try:
        from app import get_purchase_price, update_purchase_price
        
        # Probar obtener precio de compra
        precio = get_purchase_price('freefire_latam', 1)
        print(f"✅ get_purchase_price funciona: ${precio:.2f}")
        
        # Probar actualizar precio de compra
        success = update_purchase_price('freefire_latam', 1, 0.60)
        if success:
            print("✅ update_purchase_price funciona correctamente")
            
            # Verificar que se actualizó
            nuevo_precio = get_purchase_price('freefire_latam', 1)
            if abs(nuevo_precio - 0.60) < 0.01:
                print(f"✅ Precio actualizado correctamente: ${nuevo_precio:.2f}")
            else:
                print(f"❌ Precio no se actualizó correctamente: ${nuevo_precio:.2f}")
                return False
        else:
            print("❌ update_purchase_price falló")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Error en funciones de rentabilidad: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Iniciando pruebas de compatibilidad con Render...")
    
    # Limpiar variable de entorno al inicio
    if 'RENDER' in os.environ:
        del os.environ['RENDER']
    
    # Test 1: Configuración de base de datos
    if test_render_db_path():
        print("✅ Test 1 PASADO: Configuración de base de datos")
    else:
        print("❌ Test 1 FALLIDO: Configuración de base de datos")
        sys.exit(1)
    
    # Test 2: Funciones de rentabilidad
    if test_profitability_functions():
        print("✅ Test 2 PASADO: Funciones de rentabilidad")
    else:
        print("❌ Test 2 FALLIDO: Funciones de rentabilidad")
        sys.exit(1)
    
    print("\n🎉 TODOS LOS TESTS PASARON - Sistema listo para Render")
    
    # Limpiar variable de entorno al final
    if 'RENDER' in os.environ:
        del os.environ['RENDER']
