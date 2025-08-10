import sqlite3
import logging
from datetime import datetime

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PinManager:
    """Gestor de pines que maneja solo stock local"""
    
    def __init__(self, database_path):
        self.database_path = database_path
        
    def get_db_connection(self):
        """Obtiene una conexión a la base de datos"""
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_local_stock(self, monto_id=None):
        """Obtiene el stock local de pines"""
        conn = self.get_db_connection()
        
        if monto_id:
            # Stock para un monto específico
            count = conn.execute('''
                SELECT COUNT(*) FROM pines_freefire 
                WHERE monto_id = ? AND usado = FALSE
            ''', (monto_id,)).fetchone()[0]
            conn.close()
            return count
        else:
            # Stock para todos los montos
            stock = {}
            for i in range(1, 10):
                count = conn.execute('''
                    SELECT COUNT(*) FROM pines_freefire 
                    WHERE monto_id = ? AND usado = FALSE
                ''', (i,)).fetchone()[0]
                stock[i] = count
            conn.close()
            return stock
    
    def get_local_pin(self, monto_id):
        """Obtiene un pin del stock local"""
        conn = self.get_db_connection()
        pin = conn.execute('''
            SELECT * FROM pines_freefire 
            WHERE monto_id = ? AND usado = FALSE 
            LIMIT 1
        ''', (monto_id,)).fetchone()
        conn.close()
        return pin
    
    def remove_local_pin(self, pin_id):
        """Elimina un pin del stock local"""
        conn = self.get_db_connection()
        conn.execute('DELETE FROM pines_freefire WHERE id = ?', (pin_id,))
        conn.commit()
        conn.close()
    
    def add_local_pin(self, monto_id, pin_code, source='manual'):
        """Añade un pin al stock local"""
        conn = self.get_db_connection()
        try:
            # Verificar si el pin ya existe
            existing = conn.execute('''
                SELECT id FROM pines_freefire 
                WHERE pin_codigo = ? AND monto_id = ?
            ''', (pin_code, monto_id)).fetchone()
            
            if existing:
                conn.close()
                return False, "Pin ya existe en el stock"
            
            # Agregar pin
            conn.execute('''
                INSERT INTO pines_freefire (monto_id, pin_codigo)
                VALUES (?, ?)
            ''', (monto_id, pin_code))
            conn.commit()
            conn.close()
            
            logger.info(f"Pin agregado al stock local - Monto: {monto_id}")
            return True, "Pin agregado exitosamente"
            
        except Exception as e:
            conn.rollback()
            conn.close()
            logger.error(f"Error al agregar pin local: {str(e)}")
            return False, f"Error al agregar pin: {str(e)}"
    
    def request_pin(self, monto_id):
        """
        Solicita un pin del stock local únicamente
        
        Args:
            monto_id (int): ID del monto (1-9)
            
        Returns:
            dict: Resultado de la operación
        """
        try:
            logger.info(f"Solicitando pin para monto_id {monto_id}")
            
            # Verificar stock local
            local_stock = self.get_local_stock(monto_id)
            logger.info(f"Stock local para monto {monto_id}: {local_stock}")
            
            if local_stock > 0:
                # Hay stock local disponible
                local_pin = self.get_local_pin(monto_id)
                if local_pin:
                    # Eliminar pin del stock local
                    self.remove_local_pin(local_pin['id'])
                    
                    logger.info(f"Pin obtenido del stock local - Monto: {monto_id}")
                    return {
                        'status': 'success',
                        'pin_code': local_pin['pin_codigo'],
                        'monto_id': monto_id,
                        'source': 'local_stock',
                        'timestamp': datetime.now().isoformat(),
                        'stock_remaining': local_stock - 1
                    }
            
            # No hay stock local
            logger.info(f"Sin stock local para monto {monto_id}")
            return {
                'status': 'error',
                'message': 'Sin stock disponible',
                'error_type': 'no_stock',
                'local_stock': local_stock
            }
                
        except Exception as e:
            logger.error(f"Error inesperado al solicitar pin: {str(e)}")
            return {
                'status': 'error',
                'message': f'Error inesperado: {str(e)}',
                'error_type': 'unexpected'
            }
    
    def request_multiple_pins(self, monto_id, cantidad):
        """
        Solicita múltiples pines del stock local únicamente
        
        Args:
            monto_id (int): ID del monto (1-9)
            cantidad (int): Cantidad de pines solicitados
            
        Returns:
            dict: Resultado de la operación
        """
        try:
            logger.info(f"Solicitando {cantidad} pines para monto_id {monto_id}")
            
            if cantidad <= 0:
                return {
                    'status': 'error',
                    'message': 'La cantidad debe ser mayor a 0',
                    'error_type': 'validation'
                }
            
            local_stock = self.get_local_stock(monto_id)
            
            if local_stock < cantidad:
                return {
                    'status': 'error',
                    'message': f'Stock insuficiente. Disponible: {local_stock}, Solicitado: {cantidad}',
                    'error_type': 'insufficient_stock',
                    'local_stock': local_stock,
                    'cantidad_solicitada': cantidad
                }
            
            pines_obtenidos = []
            
            # Obtener pines del stock local
            for i in range(cantidad):
                local_pin = self.get_local_pin(monto_id)
                if local_pin:
                    self.remove_local_pin(local_pin['id'])
                    pines_obtenidos.append({
                        'pin_code': local_pin['pin_codigo'],
                        'source': 'local_stock'
                    })
                else:
                    logger.warning(f"Pin local esperado no encontrado en iteración {i+1}")
                    break
            
            # Resultado final
            if len(pines_obtenidos) == cantidad:
                return {
                    'status': 'success',
                    'pins': pines_obtenidos,
                    'cantidad_solicitada': cantidad,
                    'cantidad_obtenida': len(pines_obtenidos),
                    'monto_id': monto_id,
                    'timestamp': datetime.now().isoformat()
                }
            else:
                return {
                    'status': 'error',
                    'message': f'Solo se pudieron obtener {len(pines_obtenidos)} de {cantidad} pines',
                    'error_type': 'partial_stock',
                    'cantidad_solicitada': cantidad,
                    'cantidad_obtenida': len(pines_obtenidos),
                    'pins': pines_obtenidos
                }
                
        except Exception as e:
            logger.error(f"Error inesperado al solicitar múltiples pines: {str(e)}")
            return {
                'status': 'error',
                'message': f'Error inesperado: {str(e)}',
                'error_type': 'unexpected'
            }

def create_pin_manager(database_path):
    """Crea una instancia del gestor de pines"""
    return PinManager(database_path)
